package genai_prices

import (
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"sort"
	"strings"
	"time"

	"github.com/dlclark/regexp2"
)

// RemoteDataURL is the current v3 provider-data feed.
const RemoteDataURL = "https://raw.githubusercontent.com/pydantic/genai-prices/main/prices/new_data/v3/data.json"

var (
	// ErrProviderNotFound means no provider matched the request.
	ErrProviderNotFound = errors.New("provider not found")
	// ErrModelNotFound means no model matched the request.
	ErrModelNotFound = errors.New("model not found")
	// ErrExtractorNotFound means a provider has no matching usage extractor.
	ErrExtractorNotFound = errors.New("usage extractor not found")
	// ErrInvalidUsage means usage values are invalid or internally inconsistent.
	ErrInvalidUsage = errors.New("invalid usage")
	// ErrInvalidData means provider data could not be decoded or validated.
	ErrInvalidData = errors.New("invalid provider data")
)

// UsageKey identifies a value reported by a provider.
type UsageKey string

// Usage contains the values reported for one API call.
type Usage map[UsageKey]float64

type wireUnitDef struct {
	PriceKey   string
	Per        uint64
	Dimensions map[string]string
}

type orderedWireUnits struct {
	Order                 []UsageKey
	Values                map[UsageKey]wireUnitDef
	CompatibilityWarnings []string
}

// PriceRequest describes one price calculation.
type PriceRequest struct {
	Usage          Usage
	Model          string
	ProviderID     string
	ProviderAPIURL string
	Timestamp      time.Time
}

// PriceCalculation contains prices in US dollars and the matched identifiers.
type PriceCalculation struct {
	InputPrice  float64
	OutputPrice float64
	TotalPrice  float64
	ProviderID  string
	ModelID     string
	Warnings    []string
}

// ExtractRequest describes usage extraction from a raw JSON response.
type ExtractRequest struct {
	ResponseJSON   []byte
	ProviderID     string
	ProviderAPIURL string
	APIFlavor      string
}

// ExtractedUsage contains usage and model information read from a response.
type ExtractedUsage struct {
	Usage      Usage
	Model      string
	ProviderID string
	Warnings   []string
}

type provider struct {
	ID                     string           `json:"id"`
	Name                   string           `json:"name"`
	APIPattern             string           `json:"api_pattern"`
	ModelMatch             *matchLogic      `json:"model_match"`
	ProviderMatch          *matchLogic      `json:"provider_match"`
	Extractors             []usageExtractor `json:"extractors"`
	FallbackModelProviders []string         `json:"fallback_model_providers"`
	Models                 []model          `json:"models"`
	apiRegex               *regexp2.Regexp
}

type wireProvider struct {
	ID                     string               `json:"id"`
	Name                   string               `json:"name"`
	PricingURLs            []string             `json:"pricing_urls"`
	APIPattern             string               `json:"api_pattern"`
	Description            *string              `json:"description"`
	PriceComments          *string              `json:"price_comments"`
	ModelMatch             *matchLogic          `json:"model_match"`
	ProviderMatch          *matchLogic          `json:"provider_match"`
	Extractors             []wireUsageExtractor `json:"extractors"`
	FallbackModelProviders []string             `json:"fallback_model_providers"`
	Models                 []wireModel          `json:"models"`
}

type model struct {
	ID     string      `json:"id"`
	Match  matchLogic  `json:"match"`
	Prices modelPrices `json:"prices"`
}

type wireModel struct {
	ID            string          `json:"id"`
	Name          *string         `json:"name"`
	Description   *string         `json:"description"`
	Match         matchLogic      `json:"match"`
	ContextWindow json.RawMessage `json:"context_window"`
	PriceComments *string         `json:"price_comments"`
	Prices        modelPrices     `json:"prices"`
	Deprecated    *bool           `json:"deprecated"`
}

type modelPrices struct {
	direct      modelPrice
	conditional []conditionalPrice
}

func (p *modelPrices) UnmarshalJSON(data []byte) error {
	data = trimSpace(data)
	p.direct = nil
	p.conditional = nil
	if len(data) > 0 && data[0] == '[' {
		return json.Unmarshal(data, &p.conditional)
	}
	if len(data) > 0 && data[0] == '{' {
		return json.Unmarshal(data, &p.direct)
	}
	return errors.New("prices must be an object or array")
}

type modelPrice map[string]priceValue

type priceValue struct {
	base   float64
	tiers  []tier
	tiered bool
}

type tier struct {
	Start int64   `json:"start"`
	Price float64 `json:"price"`
}

func (t *tier) UnmarshalJSON(data []byte) error {
	var value struct {
		Start *int64   `json:"start"`
		Price *float64 `json:"price"`
	}
	if err := json.Unmarshal(data, &value); err != nil {
		return err
	}
	if value.Start == nil || value.Price == nil {
		return errors.New("tier must contain start and price")
	}
	t.Start = *value.Start
	t.Price = *value.Price
	return nil
}

func (p *priceValue) UnmarshalJSON(data []byte) error {
	data = trimSpace(data)
	if len(data) == 0 {
		return errors.New("empty price")
	}
	if data[0] != '{' {
		if data[0] == 'n' || data[0] == '"' || data[0] == '[' {
			return errors.New("price must be a number or tiered-price object")
		}
		var base float64
		if err := json.Unmarshal(data, &base); err != nil {
			return err
		}
		p.base = base
		return nil
	}

	var value struct {
		Base  *float64 `json:"base"`
		Tiers *[]tier  `json:"tiers"`
	}
	if err := json.Unmarshal(data, &value); err != nil {
		return err
	}
	if value.Base == nil || value.Tiers == nil {
		return errors.New("tiered price must contain base and tiers")
	}
	sort.Slice(*value.Tiers, func(left, right int) bool {
		return (*value.Tiers)[left].Start < (*value.Tiers)[right].Start
	})
	p.base = *value.Base
	p.tiers = *value.Tiers
	p.tiered = true
	return nil
}

type conditionalPrice struct {
	Constraint *priceConstraint `json:"constraint"`
	Prices     modelPrice       `json:"prices"`
}

func (p *conditionalPrice) UnmarshalJSON(data []byte) error {
	var value struct {
		Constraint json.RawMessage `json:"constraint"`
		Prices     json.RawMessage `json:"prices"`
	}
	if err := json.Unmarshal(data, &value); err != nil {
		return err
	}
	if len(value.Prices) == 0 || string(trimSpace(value.Prices)) == "null" {
		return errors.New("conditional price must contain prices")
	}
	if err := json.Unmarshal(value.Prices, &p.Prices); err != nil {
		return err
	}
	if len(value.Constraint) > 0 {
		if string(trimSpace(value.Constraint)) == "null" {
			return errors.New("constraint must be an object")
		}
		var constraint priceConstraint
		if err := json.Unmarshal(value.Constraint, &constraint); err != nil {
			return err
		}
		p.Constraint = &constraint
	}
	return nil
}

type priceConstraint struct {
	StartDate string `json:"start_date"`
	StartTime string `json:"start_time"`
	EndTime   string `json:"end_time"`
	date      time.Time
	start     float64
	end       float64
}

func (c *priceConstraint) UnmarshalJSON(data []byte) error {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		return err
	}
	for key := range fields {
		if key != "start_date" && key != "start_time" && key != "end_time" && key != "type" {
			return fmt.Errorf("unknown price constraint field %q", key)
		}
	}
	var value struct {
		StartDate string  `json:"start_date"`
		StartTime string  `json:"start_time"`
		EndTime   string  `json:"end_time"`
		Type      *string `json:"type"`
	}
	if err := json.Unmarshal(data, &value); err != nil {
		return err
	}
	if _, found := fields["type"]; found {
		if value.Type == nil {
			return errors.New("price constraint type must be a string")
		}
		validStartDate := *value.Type == "start_date" && value.StartDate != "" && value.StartTime == "" && value.EndTime == ""
		validTimeOfDay := *value.Type == "time_of_date" &&
			value.StartDate == "" && value.StartTime != "" && value.EndTime != ""
		if !validStartDate && !validTimeOfDay {
			return errors.New("price constraint type does not match its fields")
		}
	}
	c.StartDate = value.StartDate
	c.StartTime = value.StartTime
	c.EndTime = value.EndTime
	return nil
}

const regexMatchTimeout = 100 * time.Millisecond

type matchLogic struct {
	And        []matchLogic `json:"and"`
	Or         []matchLogic `json:"or"`
	Contains   *string      `json:"contains"`
	EndsWith   *string      `json:"ends_with"`
	Equals     *string      `json:"equals"`
	Regex      *string      `json:"regex"`
	StartsWith *string      `json:"starts_with"`
	compiled   *regexp2.Regexp
}

func (logic *matchLogic) compile() error {
	count := 0
	if logic.And != nil {
		count++
		for index := range logic.And {
			if err := logic.And[index].compile(); err != nil {
				return err
			}
		}
	}
	if logic.Or != nil {
		count++
		for index := range logic.Or {
			if err := logic.Or[index].compile(); err != nil {
				return err
			}
		}
	}
	for _, value := range []*string{logic.Contains, logic.EndsWith, logic.Equals, logic.Regex, logic.StartsWith} {
		if value != nil {
			count++
		}
	}
	if count != 1 {
		return fmt.Errorf("match logic must contain exactly one operation")
	}
	if logic.Regex != nil {
		compiled, err := regexp2.Compile(*logic.Regex, regexp2.None)
		if err != nil {
			return fmt.Errorf("compile regex %q: %w", *logic.Regex, err)
		}
		compiled.MatchTimeout = regexMatchTimeout
		logic.compiled = compiled
	}
	return nil
}

func (logic *matchLogic) matches(text string) (bool, error) {
	switch {
	case logic.And != nil:
		for index := range logic.And {
			matched, err := logic.And[index].matches(text)
			if err != nil || !matched {
				return matched, err
			}
		}
		return true, nil
	case logic.Or != nil:
		for index := range logic.Or {
			matched, err := logic.Or[index].matches(text)
			if err != nil {
				return false, err
			}
			if matched {
				return true, nil
			}
		}
		return false, nil
	case logic.Contains != nil:
		return strings.Contains(strings.ToLower(text), strings.ToLower(*logic.Contains)), nil
	case logic.EndsWith != nil:
		return strings.HasSuffix(strings.ToLower(text), strings.ToLower(*logic.EndsWith)), nil
	case logic.Equals != nil:
		return strings.EqualFold(text, *logic.Equals), nil
	case logic.Regex != nil:
		return logic.compiled.MatchString(text)
	case logic.StartsWith != nil:
		return strings.HasPrefix(strings.ToLower(text), strings.ToLower(*logic.StartsWith)), nil
	default:
		return false, errors.New("uncompiled match logic")
	}
}

type usageExtractor struct {
	APIFlavor string                  `json:"api_flavor"`
	Root      extractPath             `json:"root"`
	ModelPath extractPath             `json:"model_path"`
	Mappings  []usageExtractorMapping `json:"mappings"`
}

type wireUsageExtractor struct {
	Root      extractPath                 `json:"root"`
	Mappings  []wireUsageExtractorMapping `json:"mappings"`
	APIFLavor json.RawMessage             `json:"api_flavor"`
	ModelPath json.RawMessage             `json:"model_path"`
}

type usageExtractorMapping struct {
	Path     extractPath `json:"path"`
	Dest     UsageKey    `json:"dest"`
	Required bool        `json:"required"`
}

type wireUsageExtractorMapping struct {
	Path     extractPath     `json:"path"`
	Dest     UsageKey        `json:"dest"`
	Required json.RawMessage `json:"required"`
}

type wrappedProviderData struct {
	Units     orderedWireUnits `json:"units"`
	Providers json.RawMessage  `json:"providers"`
}

type decodedProviders struct {
	Values                []provider
	CompatibilityWarnings []string
}

type extractPath []pathStep

func (path *extractPath) UnmarshalJSON(data []byte) error {
	data = trimSpace(data)
	var single string
	if len(data) > 0 && data[0] == '"' {
		if err := json.Unmarshal(data, &single); err != nil {
			return err
		}
		*path = extractPath{{key: &single}}
		return nil
	}
	if len(data) == 0 || data[0] != '[' {
		return errors.New("extract path must be a string or array")
	}
	var values []json.RawMessage
	if err := json.Unmarshal(data, &values); err != nil {
		return err
	}
	steps := make(extractPath, 0, len(values))
	for _, value := range values {
		if len(value) > 0 && value[0] == '"' {
			var key string
			if err := json.Unmarshal(value, &key); err != nil {
				return err
			}
			steps = append(steps, pathStep{key: &key})
			continue
		}
		var match arrayMatch
		if err := json.Unmarshal(value, &match); err != nil {
			return fmt.Errorf("decode path step: %w", err)
		}
		steps = append(steps, pathStep{arrayMatch: &match})
	}
	*path = steps
	return nil
}

type pathStep struct {
	key        *string
	arrayMatch *arrayMatch
}

type arrayMatch struct {
	Type  string     `json:"type"`
	Field string     `json:"field"`
	Match matchLogic `json:"match"`
}

func validateNumber(label string, value float64) error {
	if math.IsNaN(value) || math.IsInf(value, 0) || value < 0 {
		return fmt.Errorf("%w: %s must be a finite non-negative number", ErrInvalidUsage, label)
	}
	return nil
}

func calculationWarnings(usage Usage, prices modelPrice, registry *unitRegistry) []string {
	usageKeys := make([]string, 0)
	for key := range usage {
		if !registry.isReported(key) {
			usageKeys = append(usageKeys, string(key))
		}
	}
	priceKeys := make([]string, 0)
	for key := range prices {
		if registry.byPriceKey[key] == nil {
			priceKeys = append(priceKeys, key)
		}
	}
	warnings := make([]string, 0, 2)
	if len(usageKeys) > 0 {
		sort.Strings(usageKeys)
		warnings = append(warnings, "Unsupported usage key for standard pricing: "+strings.Join(usageKeys, ", "))
	}
	if len(priceKeys) > 0 {
		sort.Strings(priceKeys)
		warnings = append(warnings, "Unsupported price key for standard pricing: "+strings.Join(priceKeys, ", "))
	}
	return warnings
}

func trimSpace(data []byte) []byte {
	return []byte(strings.TrimSpace(string(data)))
}
