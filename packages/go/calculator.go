package genai_prices

import (
	"encoding/json"
	"fmt"
	"maps"
	"math"
	"strings"
	"time"

	"github.com/dlclark/regexp2"
)

// Calculator calculates prices using one immutable provider-data snapshot.
type Calculator struct {
	providers []*provider
	registry  *unitRegistry
}

var bundledCalculator = mustNewCalculator()

// NewCalculator constructs a calculator using the data bundled with this release.
func NewCalculator() (*Calculator, error) {
	return NewCalculatorFromJSON(bundledProviderData)
}

// NewCalculatorFromJSON constructs a calculator using a v2 provider-data payload.
func NewCalculatorFromJSON(data []byte) (*Calculator, error) {
	var decoded []provider
	if err := json.Unmarshal(data, &decoded); err != nil {
		return nil, fmt.Errorf("%w: %v", ErrInvalidData, err)
	}
	if decoded == nil {
		return nil, fmt.Errorf("%w: expected a provider array", ErrInvalidData)
	}

	providers := make([]*provider, len(decoded))
	for index := range decoded {
		providers[index] = &decoded[index]
	}
	calculator := &Calculator{providers: providers, registry: newUnitRegistry(bundledUnits)}
	if err := calculator.validate(); err != nil {
		return nil, fmt.Errorf("%w: %v", ErrInvalidData, err)
	}
	return calculator, nil
}

// Calculate calculates a price using the bundled provider data.
func Calculate(request PriceRequest) (PriceCalculation, error) {
	return bundledCalculator.Calculate(request)
}

// Calculate calculates a price using this calculator's provider-data snapshot.
func (calculator *Calculator) Calculate(request PriceRequest) (PriceCalculation, error) {
	if calculator == nil {
		return PriceCalculation{}, fmt.Errorf("%w: calculator is nil", ErrInvalidData)
	}
	providerID := strings.TrimSpace(request.ProviderID)
	if providerID != "" && request.ProviderAPIURL != "" {
		return PriceCalculation{}, fmt.Errorf("%w: provider ID and provider API URL are mutually exclusive", ErrInvalidUsage)
	}
	modelID := strings.ToLower(strings.TrimSpace(request.Model))
	if modelID == "" {
		return PriceCalculation{}, fmt.Errorf("%w: model is required", ErrModelNotFound)
	}
	if strings.EqualFold(providerID, "litellm") {
		actualProviderID, actualModelID, found := strings.Cut(modelID, "/")
		if found && actualProviderID != "" && actualModelID != "" {
			actualProvider, err := findProviderByID(calculator.providers, actualProviderID)
			if err != nil {
				return PriceCalculation{}, err
			}
			if actualProvider != nil {
				providerID = actualProviderID
				modelID = actualModelID
			}
		}
	}

	selected, err := findProvider(calculator.providers, modelID, providerID, request.ProviderAPIURL)
	if err != nil {
		return PriceCalculation{}, fmt.Errorf("match provider: %w", err)
	}
	if selected == nil {
		return PriceCalculation{}, fmt.Errorf(
			"%w: model=%q provider_id=%q provider_api_url=%q",
			ErrProviderNotFound,
			modelID,
			providerID,
			request.ProviderAPIURL,
		)
	}
	matchedModel, err := findModel(calculator.providers, selected, modelID)
	if err != nil {
		return PriceCalculation{}, fmt.Errorf("match model: %w", err)
	}
	if matchedModel == nil {
		return PriceCalculation{}, fmt.Errorf("%w: %q in provider %q", ErrModelNotFound, modelID, selected.ID)
	}
	timestamp := request.Timestamp
	if timestamp.IsZero() {
		timestamp = time.Now()
	}
	// Price variants are one provider's rates, so they don't apply to a model borrowed through
	// fallback_model_providers, e.g. OpenAI's flex rates to a request priced against Azure.
	priceContext := request.PriceContext
	if len(priceContext) > 0 && len(matchedModel.PriceVariants) > 0 && !ownsModel(selected, matchedModel) {
		priceContext = nil
	}
	prices, variant := resolveModelPrice(matchedModel, timestamp, priceContext)
	usage := request.Usage
	if usage == nil {
		usage = Usage{}
	}
	for key, value := range usage {
		if calculator.registry.isReported(key) {
			if err := validateNumber(string(key), value); err != nil {
				return PriceCalculation{}, err
			}
		}
	}
	usage = applyProviderBilling(selected, matchedModel, usage)
	inputPrice, outputPrice, totalPrice, err := calculateModelPrice(usage, prices, calculator.registry)
	if err != nil {
		return PriceCalculation{}, err
	}
	calculation := PriceCalculation{
		InputPrice:  inputPrice,
		OutputPrice: outputPrice,
		TotalPrice:  totalPrice,
		ProviderID:  selected.ID,
		ModelID:     matchedModel.ID,
		Warnings:    calculationWarnings(request.Usage, prices, calculator.registry),
	}
	if variant != nil {
		// a copy, so a caller changing the result can't change the calculator's data
		calculation.PriceVariant = &PriceVariant{When: deepCopyJSON(variant.When).(map[string]any)}
	}
	return calculation, nil
}

func (calculator *Calculator) validate() error {
	providerIDs := make(map[string]struct{}, len(calculator.providers))
	for _, provider := range calculator.providers {
		if provider.ID == "" || provider.Name == "" || provider.APIPattern == "" {
			return fmt.Errorf("provider id, name, and api_pattern are required")
		}
		if provider.ID != strings.ToLower(strings.TrimSpace(provider.ID)) {
			return fmt.Errorf("provider ID %q must be lowercase without surrounding whitespace", provider.ID)
		}
		if _, duplicate := providerIDs[provider.ID]; duplicate {
			return fmt.Errorf("duplicate provider ID %q", provider.ID)
		}
		providerIDs[provider.ID] = struct{}{}
		compiled, err := regexp2.Compile("^(?:"+provider.APIPattern+")", regexp2.None)
		if err != nil {
			return fmt.Errorf("provider %q API pattern: %w", provider.ID, err)
		}
		compiled.MatchTimeout = regexMatchTimeout
		provider.apiRegex = compiled
		for _, logic := range []*matchLogic{provider.ModelMatch, provider.ProviderMatch} {
			if logic != nil {
				if err := logic.compile(); err != nil {
					return fmt.Errorf("provider %q match logic: %w", provider.ID, err)
				}
			}
		}
		for extractorIndex := range provider.Extractors {
			extractor := &provider.Extractors[extractorIndex]
			if extractor.APIFlavor == "" {
				extractor.APIFlavor = "default"
			}
			if extractor.ModelPath == nil {
				extractor.ModelPath = extractPath{{key: stringPointer("model")}}
			}
			if err := validateExtractPath(extractor.Root); err != nil {
				return fmt.Errorf("provider %q extractor %q root: %w", provider.ID, extractor.APIFlavor, err)
			}
			if err := validateExtractPath(extractor.ModelPath); err != nil {
				return fmt.Errorf("provider %q extractor %q model path: %w", provider.ID, extractor.APIFlavor, err)
			}
			for mappingIndex := range extractor.Mappings {
				mapping := &extractor.Mappings[mappingIndex]
				if err := validateExtractPath(mapping.Path); err != nil {
					return fmt.Errorf("provider %q extractor %q mapping %d: %w", provider.ID, extractor.APIFlavor, mappingIndex, err)
				}
			}
		}
		modelIDs := make(map[string]struct{}, len(provider.Models))
		for modelIndex := range provider.Models {
			model := &provider.Models[modelIndex]
			if model.ID == "" {
				return fmt.Errorf("provider %q has a model without an ID", provider.ID)
			}
			if _, duplicate := modelIDs[model.ID]; duplicate {
				return fmt.Errorf("provider %q has duplicate model ID %q", provider.ID, model.ID)
			}
			modelIDs[model.ID] = struct{}{}
			if err := model.Match.compile(); err != nil {
				return fmt.Errorf("provider %q model %q match logic: %w", provider.ID, model.ID, err)
			}
			if err := validatePriceVariants(model, calculator.registry); err != nil {
				return fmt.Errorf("provider %q model %q price variants: %w", provider.ID, model.ID, err)
			}
			if model.Prices.conditional == nil {
				if err := validateModelPrice(model.Prices.direct, calculator.registry); err != nil {
					return fmt.Errorf("provider %q model %q prices: %w", provider.ID, model.ID, err)
				}
				continue
			}
			if len(model.Prices.conditional) == 0 {
				return fmt.Errorf("provider %q model %q has no conditional prices", provider.ID, model.ID)
			}
			unconstrainedPrices := 0
			for conditionalIndex := range model.Prices.conditional {
				conditional := &model.Prices.conditional[conditionalIndex]
				if conditional.Constraint != nil {
					if err := parseConstraint(conditional.Constraint); err != nil {
						return fmt.Errorf("provider %q model %q constraint: %w", provider.ID, model.ID, err)
					}
				} else {
					unconstrainedPrices++
				}
				if err := validateModelPrice(conditional.Prices, calculator.registry); err != nil {
					return fmt.Errorf("provider %q model %q conditional prices: %w", provider.ID, model.ID, err)
				}
			}
			if unconstrainedPrices != 1 {
				return fmt.Errorf(
					"provider %q model %q must have exactly one unconstrained price",
					provider.ID,
					model.ID,
				)
			}
		}
	}
	return nil
}

// deepCopyJSON copies a value decoded from JSON, including its nested maps and lists.
func deepCopyJSON(value any) any {
	switch value := value.(type) {
	case map[string]any:
		copied := make(map[string]any, len(value))
		for key, item := range value {
			copied[key] = deepCopyJSON(item)
		}
		return copied
	case []any:
		copied := make([]any, len(value))
		for index, item := range value {
			copied[index] = deepCopyJSON(item)
		}
		return copied
	default:
		return value
	}
}

func ownsModel(provider *provider, model *model) bool {
	for index := range provider.Models {
		if &provider.Models[index] == model {
			return true
		}
	}
	return false
}

// validatePriceVariants checks each variant's constraint, and its prices laid over every standard price.
func validatePriceVariants(model *model, registry *unitRegistry) error {
	standardPrices := []modelPrice{model.Prices.direct}
	if model.Prices.conditional != nil {
		standardPrices = standardPrices[:0]
		for _, conditional := range model.Prices.conditional {
			standardPrices = append(standardPrices, conditional.Prices)
		}
	}
	for variantIndex := range model.PriceVariants {
		variant := &model.PriceVariants[variantIndex]
		if variant.Constraint != nil {
			if err := parseConstraint(variant.Constraint); err != nil {
				return fmt.Errorf("constraint: %w", err)
			}
		}
		for _, standard := range standardPrices {
			merged := maps.Clone(standard)
			maps.Copy(merged, variant.Prices)
			if err := validateModelPrice(merged, registry); err != nil {
				return err
			}
		}
	}
	return nil
}

func applyProviderBilling(provider *provider, model *model, usage Usage) Usage {
	if provider.ID != "groq" || (model.ID != "whisper-large-v3" && model.ID != "whisper-large-v3-turbo") {
		return usage
	}
	audio, hasAudio := usage[UsageAudioSeconds]
	inputAudio, hasInputAudio := usage[UsageInputAudioSeconds]
	reported := 0.0
	found := false
	if hasAudio && audio != 0 {
		reported, found = audio, true
	} else if hasInputAudio {
		reported, found = inputAudio, true
	}
	if !found {
		return usage
	}
	billed := reported
	if billed > 0 {
		billed = math.Max(billed, 10)
	}
	copy := make(Usage, len(usage)+2)
	for key, value := range usage {
		copy[key] = value
	}
	copy[UsageAudioSeconds] = billed
	copy[UsageInputAudioSeconds] = billed
	return copy
}

func validateExtractPath(path extractPath) error {
	if len(path) == 0 || path[len(path)-1].key == nil {
		return fmt.Errorf("path must end with a string")
	}
	for index := range path {
		step := &path[index]
		switch {
		case step.key != nil && step.arrayMatch == nil:
			continue
		case step.key == nil && step.arrayMatch != nil:
			if step.arrayMatch.Type != "array-match" || step.arrayMatch.Field == "" {
				return fmt.Errorf("invalid array-match step")
			}
			if err := step.arrayMatch.Match.compile(); err != nil {
				return err
			}
		default:
			return fmt.Errorf("path step must contain one operation")
		}
	}
	return nil
}

func stringPointer(value string) *string {
	return &value
}

func mustNewCalculator() *Calculator {
	calculator, err := NewCalculator()
	if err != nil {
		panic(err)
	}
	return calculator
}
