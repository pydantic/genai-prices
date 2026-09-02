package genai_prices

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"math/big"
	"sort"
)

func decodeCalculatorData(data []byte) (*Calculator, error) {
	switch rawKind(data) {
	case '{':
		return decodeWrappedCalculatorData(data)
	case '[':
		return decodeLegacyCalculatorData(data)
	default:
		return nil, errors.New("expected a wrapped object or provider array")
	}
}

func decodeWrappedCalculatorData(data []byte) (*Calculator, error) {
	var wrapped wrappedProviderData
	if err := json.Unmarshal(data, &wrapped); err != nil {
		return nil, err
	}
	registry, err := newUntrustedUnitRegistry(wrapped.Units)
	if err != nil {
		return nil, fmt.Errorf("units: %w", err)
	}
	bundledRegistry := newUnitRegistry(bundledUnits, bundledUnitOrder)
	if err := validateUnitEvolution(bundledRegistry, registry); err != nil {
		return nil, fmt.Errorf("units: %w", err)
	}
	decoded, err := decodeWrappedProviders(wrapped.Providers, registry)
	if err != nil {
		return nil, err
	}
	warnings := append([]string(nil), wrapped.Units.CompatibilityWarnings...)
	warnings = append(warnings, decoded.CompatibilityWarnings...)
	return calculatorFromDecodedProviders(decoded.Values, registry, warnings), nil
}

func decodeLegacyCalculatorData(data []byte) (*Calculator, error) {
	registry := newUnitRegistry(bundledUnits, bundledUnitOrder)
	decoded, err := decodeLegacyProviders(data, registry)
	if err != nil {
		return nil, err
	}
	return calculatorFromDecodedProviders(decoded.Values, registry, decoded.CompatibilityWarnings), nil
}

func calculatorFromDecodedProviders(values []provider, registry *unitRegistry, warnings []string) *Calculator {
	providers := make([]*provider, len(values))
	for index := range values {
		providers[index] = &values[index]
	}
	return &Calculator{
		providers:             providers,
		registry:              registry,
		compatibilityWarnings: append([]string(nil), warnings...),
	}
}

func decodeWrappedProviders(data json.RawMessage, registry *unitRegistry) (decodedProviders, error) {
	projector := providerProjector{}
	projected, err := projector.projectProviderArray(data)
	if err != nil {
		return decodedProviders{}, err
	}
	decoded, err := decodeWireProviders(projected, registry)
	if err != nil {
		return decodedProviders{}, err
	}
	decoded.CompatibilityWarnings = append(projector.warnings, decoded.CompatibilityWarnings...)
	if err := validateDecodedProviders(decoded.Values, registry, true); err != nil {
		return decodedProviders{}, err
	}
	return decoded, nil
}

func decodeLegacyProviders(data json.RawMessage, registry *unitRegistry) (decodedProviders, error) {
	legacyData, err := projectLegacyProviderArray(data)
	if err != nil {
		return decodedProviders{}, err
	}
	decoded, err := decodeWireProviders(legacyData, registry)
	if err != nil {
		return decodedProviders{}, err
	}
	if err := validateDecodedProviders(decoded.Values, registry, false); err != nil {
		return decodedProviders{}, err
	}
	return decoded, nil
}

func projectLegacyProviderArray(data json.RawMessage) (json.RawMessage, error) {
	providers, err := rawArray(data, "providers")
	if err != nil {
		return nil, err
	}
	projected := make([]json.RawMessage, 0, len(providers))
	for index, rawProvider := range providers {
		if rawKind(rawProvider) != '{' {
			projected = append(projected, rawProvider)
			continue
		}
		providerPath := fmt.Sprintf("providers[%d]", index)
		fields, err := rawObject(rawProvider, providerPath)
		if err != nil {
			return nil, err
		}
		for _, key := range []string{"description", "price_comments", "pricing_urls"} {
			delete(fields, key)
		}
		if rawModels, found := fields["models"]; found && rawKind(rawModels) == '[' {
			models, err := rawArray(rawModels, providerPath+".models")
			if err != nil {
				return nil, err
			}
			projectedModels := make([]json.RawMessage, 0, len(models))
			for modelIndex, rawModel := range models {
				if rawKind(rawModel) != '{' {
					projectedModels = append(projectedModels, rawModel)
					continue
				}
				modelFields, err := rawObject(rawModel, fmt.Sprintf("%s.models[%d]", providerPath, modelIndex))
				if err != nil {
					return nil, err
				}
				for _, key := range []string{"context_window", "deprecated", "description", "name", "price_comments"} {
					delete(modelFields, key)
				}
				encoded, err := json.Marshal(modelFields)
				if err != nil {
					return nil, err
				}
				projectedModels = append(projectedModels, encoded)
			}
			fields["models"], err = json.Marshal(projectedModels)
			if err != nil {
				return nil, err
			}
		}
		encoded, err := json.Marshal(fields)
		if err != nil {
			return nil, err
		}
		projected = append(projected, encoded)
	}
	return json.Marshal(projected)
}

func decodeWireProviders(data json.RawMessage, registry *unitRegistry) (decodedProviders, error) {
	if registry == nil {
		return decodedProviders{}, errors.New("unit registry is required")
	}
	if rawKind(data) != '[' {
		return decodedProviders{}, errors.New("providers must be an array")
	}
	var wireProviders []wireProvider
	if err := json.Unmarshal(data, &wireProviders); err != nil {
		return decodedProviders{}, err
	}
	values := make([]provider, len(wireProviders))
	warnings := make([]string, 0)
	for index, wireProviderValue := range wireProviders {
		runtimeProviderValue, providerWarnings, err := wireProviderValue.runtimeProvider(registry)
		if err != nil {
			return decodedProviders{}, fmt.Errorf("providers[%d]: %w", index, err)
		}
		values[index] = runtimeProviderValue
		warnings = append(warnings, providerWarnings...)
	}
	return decodedProviders{Values: values, CompatibilityWarnings: warnings}, nil
}

func (value wireProvider) runtimeProvider(registry *unitRegistry) (provider, []string, error) {
	if registry == nil {
		return provider{}, nil, errors.New("unit registry is required")
	}
	extractors := make([]usageExtractor, 0, len(value.Extractors))
	warnings := make([]string, 0)
	for index, wireExtractor := range value.Extractors {
		extractor, supported, extractorWarnings, err := wireExtractor.runtimeExtractor()
		if err != nil {
			return provider{}, nil, fmt.Errorf("extractor %d: %w", index, err)
		}
		warnings = append(warnings, extractorWarnings...)
		if supported {
			extractors = append(extractors, extractor)
		}
	}
	models := make([]model, len(value.Models))
	for index, wireModelValue := range value.Models {
		models[index] = model{ID: wireModelValue.ID, Match: wireModelValue.Match, Prices: wireModelValue.Prices}
	}
	return provider{
		ID:                     value.ID,
		Name:                   value.Name,
		APIPattern:             value.APIPattern,
		ModelMatch:             value.ModelMatch,
		ProviderMatch:          value.ProviderMatch,
		Extractors:             extractors,
		FallbackModelProviders: append([]string(nil), value.FallbackModelProviders...),
		Models:                 models,
	}, warnings, nil
}

func (value wireUsageExtractor) runtimeExtractor() (usageExtractor, bool, []string, error) {
	apiFlavor := "default"
	if len(value.APIFLavor) > 0 {
		if rawKind(value.APIFLavor) != '"' || json.Unmarshal(value.APIFLavor, &apiFlavor) != nil {
			return usageExtractor{}, false, nil, errors.New("api_flavor must be a string")
		}
	}
	modelPath := extractPath{{key: stringPointer("model")}}
	if len(value.ModelPath) > 0 {
		if err := json.Unmarshal(value.ModelPath, &modelPath); err != nil {
			return usageExtractor{}, false, nil, fmt.Errorf("model_path: %w", err)
		}
	}
	mappings := make([]usageExtractorMapping, len(value.Mappings))
	for index, wireMapping := range value.Mappings {
		required := true
		if len(wireMapping.Required) > 0 {
			if rawKind(wireMapping.Required) != 't' && rawKind(wireMapping.Required) != 'f' {
				return usageExtractor{}, false, nil, fmt.Errorf("mapping %d required must be a boolean", index)
			}
			if err := json.Unmarshal(wireMapping.Required, &required); err != nil {
				return usageExtractor{}, false, nil, fmt.Errorf("mapping %d required must be a boolean: %w", index, err)
			}
		}
		mappings[index] = usageExtractorMapping{Path: wireMapping.Path, Dest: wireMapping.Dest, Required: required}
	}
	return usageExtractor{
		APIFlavor: apiFlavor,
		Root:      value.Root,
		ModelPath: modelPath,
		Mappings:  mappings,
	}, true, nil, nil
}

func validateDecodedProviders(values []provider, registry *unitRegistry, validateDestinations bool) error {
	pointers := make([]*provider, len(values))
	for index := range values {
		pointers[index] = &values[index]
	}
	calculator := &Calculator{providers: pointers, registry: registry}
	if err := calculator.validate(); err != nil {
		return err
	}
	if !validateDestinations {
		return nil
	}
	for _, providerValue := range values {
		for extractorIndex, extractor := range providerValue.Extractors {
			for mappingIndex, mapping := range extractor.Mappings {
				if !registry.isReported(mapping.Dest) {
					return fmt.Errorf(
						"provider %q extractor %d mapping %d has unknown destination %q",
						providerValue.ID,
						extractorIndex,
						mappingIndex,
						mapping.Dest,
					)
				}
			}
		}
	}
	return nil
}

type providerProjector struct {
	warnings []string
}

func (projector *providerProjector) projectProviderArray(data json.RawMessage) (json.RawMessage, error) {
	providers, err := rawArray(data, "providers")
	if err != nil {
		return nil, err
	}
	projected := make([]json.RawMessage, 0, len(providers))
	for index, rawProvider := range providers {
		value, err := projector.projectProvider(rawProvider, index)
		if err != nil {
			return nil, err
		}
		projected = append(projected, value)
	}
	return json.Marshal(projected)
}

func (projector *providerProjector) projectProvider(data json.RawMessage, providerIndex int) (json.RawMessage, error) {
	path := fmt.Sprintf("providers[%d]", providerIndex)
	fields, err := rawObject(data, path)
	if err != nil {
		return nil, err
	}
	context := providerWireContext(fields, providerIndex)
	if err := validateProviderMetadata(fields, path); err != nil {
		return nil, err
	}

	for _, field := range []string{"model_match", "provider_match"} {
		if rawMatch, found := fields[field]; found {
			matchPath := path + "." + field
			projected, supported, err := projector.projectMatch(rawMatch, matchPath)
			if err != nil {
				return nil, err
			}
			if supported {
				fields[field] = projected
			} else {
				projector.warn("match", matchPath, context)
				delete(fields, field)
			}
		}
	}

	if rawExtractors, found := fields["extractors"]; found {
		extractors, err := rawArray(rawExtractors, path+".extractors")
		if err != nil {
			return nil, err
		}
		projectedExtractors := make([]json.RawMessage, 0, len(extractors))
		for index, rawExtractor := range extractors {
			extractorPath := fmt.Sprintf("%s.extractors[%d]", path, index)
			projected, supported, err := projector.projectExtractor(rawExtractor, extractorPath, context)
			if err != nil {
				return nil, err
			}
			if supported {
				projectedExtractors = append(projectedExtractors, projected)
			}
		}
		fields["extractors"], err = json.Marshal(projectedExtractors)
		if err != nil {
			return nil, err
		}
	}

	rawModels, found := fields["models"]
	if !found {
		return nil, fmt.Errorf("%s.models is required", path)
	}
	models, err := rawArray(rawModels, path+".models")
	if err != nil {
		return nil, err
	}
	projectedModels := make([]json.RawMessage, 0, len(models))
	for index, rawModel := range models {
		modelPath := fmt.Sprintf("%s.models[%d]", path, index)
		projected, supported, err := projector.projectModel(rawModel, modelPath, context, index)
		if err != nil {
			return nil, err
		}
		if supported {
			projectedModels = append(projectedModels, projected)
		}
	}
	fields["models"], err = json.Marshal(projectedModels)
	if err != nil {
		return nil, err
	}
	return json.Marshal(fields)
}

func (projector *providerProjector) projectExtractor(
	data json.RawMessage,
	path string,
	context string,
) (json.RawMessage, bool, error) {
	fields, err := rawObject(data, path)
	if err != nil {
		return nil, false, err
	}
	_, hasRoot := fields["root"]
	_, hasMappings := fields["mappings"]
	if _, hasType := fields["type"]; hasType || (!hasRoot && !hasMappings) {
		projector.warn("extractor", path, context)
		return nil, false, nil
	}
	if !hasRoot || !hasMappings {
		return nil, false, fmt.Errorf("%s requires root and mappings", path)
	}
	projectedRoot, supported, err := projector.projectExtractPath(fields["root"], path+".root")
	if err != nil {
		return nil, false, err
	}
	if !supported {
		projector.warn("extractor", path+".root", context)
		return nil, false, nil
	}
	fields["root"] = projectedRoot
	if modelPath, found := fields["model_path"]; found {
		projectedModelPath, supported, err := projector.projectExtractPath(modelPath, path+".model_path")
		if err != nil {
			return nil, false, err
		}
		if !supported {
			projector.warn("extractor", path+".model_path", context)
			return nil, false, nil
		}
		fields["model_path"] = projectedModelPath
	}

	mappings, err := rawArray(fields["mappings"], path+".mappings")
	if err != nil {
		return nil, false, err
	}
	projectedMappings := make([]json.RawMessage, 0, len(mappings))
	for index, rawMapping := range mappings {
		mappingPath := fmt.Sprintf("%s.mappings[%d]", path, index)
		projected, supported, err := projector.projectExtractorMapping(rawMapping, mappingPath, context)
		if err != nil {
			return nil, false, err
		}
		if supported {
			projectedMappings = append(projectedMappings, projected)
		}
	}
	if len(projectedMappings) == 0 {
		return nil, false, nil
	}
	fields["mappings"], err = json.Marshal(projectedMappings)
	if err != nil {
		return nil, false, err
	}
	return marshalRawObject(fields)
}

func (projector *providerProjector) projectExtractorMapping(
	data json.RawMessage,
	path string,
	context string,
) (json.RawMessage, bool, error) {
	fields, err := rawObject(data, path)
	if err != nil {
		return nil, false, err
	}
	_, hasPath := fields["path"]
	_, hasDest := fields["dest"]
	if !hasPath && !hasDest {
		projector.warn("extractor mapping", path, context)
		return nil, false, nil
	}
	if !hasPath || !hasDest {
		return nil, false, fmt.Errorf("%s requires path and dest", path)
	}
	projectedPath, supported, err := projector.projectExtractPath(fields["path"], path+".path")
	if err != nil {
		return nil, false, err
	}
	if !supported {
		projector.warn("extractor mapping", path+".path", context)
		return nil, false, nil
	}
	fields["path"] = projectedPath
	return marshalRawObject(fields)
}

func (projector *providerProjector) projectExtractPath(data json.RawMessage, path string) (json.RawMessage, bool, error) {
	switch rawKind(data) {
	case '"':
		return data, true, nil
	case '{':
		return nil, false, nil
	case '[':
		steps, err := rawArray(data, path)
		if err != nil {
			return nil, false, err
		}
		projected := make([]json.RawMessage, 0, len(steps))
		for index, step := range steps {
			if rawKind(step) != '{' {
				projected = append(projected, step)
				continue
			}
			stepPath := fmt.Sprintf("%s[%d]", path, index)
			fields, err := rawObject(step, stepPath)
			if err != nil {
				return nil, false, err
			}
			if rawString(fields["type"]) != "array-match" {
				return nil, false, nil
			}
			if rawMatch, found := fields["match"]; found {
				projectedMatch, supported, err := projector.projectMatch(rawMatch, stepPath+".match")
				if err != nil {
					return nil, false, err
				}
				if !supported {
					return nil, false, nil
				}
				fields["match"] = projectedMatch
			}
			encoded, err := json.Marshal(fields)
			if err != nil {
				return nil, false, err
			}
			projected = append(projected, encoded)
		}
		encoded, err := json.Marshal(projected)
		return encoded, true, err
	default:
		return data, true, nil
	}
}

func (projector *providerProjector) projectMatch(data json.RawMessage, path string) (json.RawMessage, bool, error) {
	fields, err := rawObject(data, path)
	if err != nil {
		return nil, false, err
	}
	known := make([]string, 0, 1)
	for _, key := range []string{"and", "or", "contains", "ends_with", "equals", "regex", "starts_with"} {
		if _, found := fields[key]; found {
			known = append(known, key)
		}
	}
	if len(known) == 0 {
		return nil, false, nil
	}
	if len(known) != 1 || (known[0] != "and" && known[0] != "or") || rawKind(fields[known[0]]) != '[' {
		return data, true, nil
	}
	children, err := rawArray(fields[known[0]], path+"."+known[0])
	if err != nil {
		return nil, false, err
	}
	projectedChildren := make([]json.RawMessage, 0, len(children))
	for index, child := range children {
		projected, supported, err := projector.projectMatch(child, fmt.Sprintf("%s.%s[%d]", path, known[0], index))
		if err != nil {
			return nil, false, err
		}
		if !supported {
			return nil, false, nil
		}
		projectedChildren = append(projectedChildren, projected)
	}
	fields[known[0]], err = json.Marshal(projectedChildren)
	if err != nil {
		return nil, false, err
	}
	return marshalRawObject(fields)
}

func (projector *providerProjector) projectModel(
	data json.RawMessage,
	path string,
	providerContext string,
	modelIndex int,
) (json.RawMessage, bool, error) {
	fields, err := rawObject(data, path)
	if err != nil {
		return nil, false, err
	}
	context := providerContext + ", " + modelWireContext(fields, modelIndex)
	if rawMatch, found := fields["match"]; found {
		projected, supported, err := projector.projectMatch(rawMatch, path+".match")
		if err != nil {
			return nil, false, err
		}
		if !supported {
			projector.warn("match", path+".match", context)
			return nil, false, nil
		}
		fields["match"] = projected
	}
	for _, required := range []string{"id", "match", "prices"} {
		if _, found := fields[required]; !found {
			return nil, false, fmt.Errorf("%s.%s is required", path, required)
		}
	}
	if err := validateModelMetadata(fields, path); err != nil {
		return nil, false, err
	}
	projectedPrices, err := projector.projectPrices(fields["prices"], path+".prices", context)
	if err != nil {
		return nil, false, err
	}
	var projectedPriceCount int
	if rawKind(projectedPrices) == '{' {
		projectedPriceMap, err := rawObject(projectedPrices, path+".prices")
		if err != nil {
			return nil, false, err
		}
		projectedPriceCount = len(projectedPriceMap)
	} else if rawKind(projectedPrices) == '[' {
		projectedPriceList, err := rawArray(projectedPrices, path+".prices")
		if err != nil {
			return nil, false, err
		}
		projectedPriceCount = len(projectedPriceList)
	}
	if projectedPriceCount == 0 {
		return nil, false, nil
	}
	fields["prices"] = projectedPrices
	return marshalRawObject(fields)
}

func (projector *providerProjector) projectPrices(
	data json.RawMessage,
	path string,
	context string,
) (json.RawMessage, error) {
	switch rawKind(data) {
	case '{':
		return projector.projectPriceMap(data, path, context)
	case '[':
		prices, err := rawArray(data, path)
		if err != nil {
			return nil, err
		}
		projectedPrices := make([]json.RawMessage, 0, len(prices))
		for index, rawPrice := range prices {
			pricePath := fmt.Sprintf("%s[%d]", path, index)
			if rawKind(rawPrice) != '{' {
				projectedPrices = append(projectedPrices, rawPrice)
				continue
			}
			fields, err := rawObject(rawPrice, pricePath)
			if err != nil {
				return nil, err
			}
			rawPriceMap, found := fields["prices"]
			if !found {
				projector.warn("price", pricePath, context)
				continue
			}
			if rawConstraint, found := fields["constraint"]; found {
				projected, supported, err := projectConstraint(rawConstraint)
				if err != nil {
					return nil, fmt.Errorf("%s.constraint: %w", pricePath, err)
				}
				if !supported {
					projector.warn("constraint", pricePath+".constraint", context)
					continue
				}
				fields["constraint"] = projected
			}
			projectedPriceMap, err := projector.projectPriceMap(rawPriceMap, pricePath+".prices", context)
			if err != nil {
				return nil, err
			}
			projectedPriceFields, err := rawObject(projectedPriceMap, pricePath+".prices")
			if err != nil {
				return nil, err
			}
			if len(projectedPriceFields) == 0 {
				continue
			}
			fields["prices"] = projectedPriceMap
			encoded, err := json.Marshal(fields)
			if err != nil {
				return nil, err
			}
			projectedPrices = append(projectedPrices, encoded)
		}
		return json.Marshal(projectedPrices)
	default:
		return data, nil
	}
}

func (projector *providerProjector) projectPriceMap(
	data json.RawMessage,
	path string,
	context string,
) (json.RawMessage, error) {
	fields, err := rawObject(data, path)
	if err != nil {
		return nil, err
	}
	keys := make([]string, 0, len(fields))
	for key := range fields {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	for _, key := range keys {
		value := fields[key]
		if rawKind(value) != '{' {
			continue
		}
		priceFields, err := rawObject(value, path+"."+key)
		if err != nil {
			return nil, err
		}
		_, hasBase := priceFields["base"]
		_, hasTiers := priceFields["tiers"]
		if !hasBase && !hasTiers {
			projector.warn("price", path+"."+key, context)
			delete(fields, key)
		}
	}
	return json.Marshal(fields)
}

func projectConstraint(data json.RawMessage) (json.RawMessage, bool, error) {
	if rawKind(data) != '{' {
		return data, true, nil
	}
	fields, err := rawObject(data, "constraint")
	if err != nil {
		return nil, false, err
	}
	if rawType, found := fields["type"]; found {
		if rawKind(rawType) != '"' {
			return data, true, nil
		}
		typeName := rawString(rawType)
		if typeName != "start_date" && typeName != "time_of_date" {
			return nil, false, nil
		}
		return recognizedConstraint(fields), true, nil
	}
	if _, found := fields["start_date"]; found {
		return recognizedConstraint(fields), true, nil
	}
	if _, startFound := fields["start_time"]; startFound {
		return recognizedConstraint(fields), true, nil
	}
	if _, endFound := fields["end_time"]; endFound {
		return recognizedConstraint(fields), true, nil
	}
	return nil, false, nil
}

func recognizedConstraint(fields map[string]json.RawMessage) json.RawMessage {
	recognized := make(map[string]json.RawMessage)
	for _, key := range []string{"end_time", "start_date", "start_time", "type"} {
		if value, found := fields[key]; found {
			recognized[key] = value
		}
	}
	encoded, _ := json.Marshal(recognized)
	return encoded
}

func (projector *providerProjector) warn(capability, path, context string) {
	projector.warnings = append(
		projector.warnings,
		fmt.Sprintf("Unsupported %s variant at %s for %s; upgrade genai-prices for full support", capability, path, context),
	)
}

func rawArray(data json.RawMessage, path string) ([]json.RawMessage, error) {
	if rawKind(data) != '[' {
		return nil, fmt.Errorf("%s must be an array", path)
	}
	var values []json.RawMessage
	if err := json.Unmarshal(data, &values); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	return values, nil
}

func rawObject(data json.RawMessage, path string) (map[string]json.RawMessage, error) {
	if rawKind(data) != '{' {
		return nil, fmt.Errorf("%s must be an object", path)
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		return nil, fmt.Errorf("%s: %w", path, err)
	}
	return fields, nil
}

func marshalRawObject(fields map[string]json.RawMessage) (json.RawMessage, bool, error) {
	encoded, err := json.Marshal(fields)
	return encoded, true, err
}

func rawKind(data json.RawMessage) byte {
	trimmed := bytes.TrimSpace(data)
	if len(trimmed) == 0 {
		return 0
	}
	return trimmed[0]
}

func rawString(data json.RawMessage) string {
	if rawKind(data) != '"' {
		return ""
	}
	var value string
	if err := json.Unmarshal(data, &value); err != nil {
		return ""
	}
	return value
}

func providerWireContext(fields map[string]json.RawMessage, index int) string {
	if id := rawString(fields["id"]); id != "" {
		return fmt.Sprintf("provider %q", id)
	}
	return fmt.Sprintf("provider index %d", index)
}

func modelWireContext(fields map[string]json.RawMessage, index int) string {
	if id := rawString(fields["id"]); id != "" {
		return fmt.Sprintf("model %q", id)
	}
	return fmt.Sprintf("model index %d", index)
}

func validateProviderMetadata(fields map[string]json.RawMessage, path string) error {
	for _, required := range []string{"api_pattern", "id", "name"} {
		if _, found := fields[required]; !found {
			return fmt.Errorf("%s.%s is required", path, required)
		}
	}
	for _, key := range []string{"description", "price_comments"} {
		if err := validateOptionalString(fields, key, path); err != nil {
			return err
		}
	}
	for _, key := range []string{"fallback_model_providers", "pricing_urls"} {
		if err := validateOptionalStringArray(fields, key, path); err != nil {
			return err
		}
	}
	return nil
}

func validateModelMetadata(fields map[string]json.RawMessage, path string) error {
	for _, key := range []string{"description", "name", "price_comments"} {
		if err := validateOptionalString(fields, key, path); err != nil {
			return err
		}
	}
	if value, found := fields["deprecated"]; found {
		if rawKind(value) != 't' && rawKind(value) != 'f' {
			return fmt.Errorf("%s.deprecated must be a boolean", path)
		}
		var decoded bool
		if err := json.Unmarshal(value, &decoded); err != nil {
			return fmt.Errorf("%s.deprecated must be a boolean: %w", path, err)
		}
	}
	if value, found := fields["context_window"]; found && !rawJSONInteger(value) {
		return fmt.Errorf("%s.context_window must be an integer", path)
	}
	return nil
}

func validateOptionalString(fields map[string]json.RawMessage, key, path string) error {
	value, found := fields[key]
	if !found {
		return nil
	}
	if rawKind(value) != '"' {
		return fmt.Errorf("%s.%s must be a string", path, key)
	}
	var decoded string
	if err := json.Unmarshal(value, &decoded); err != nil {
		return fmt.Errorf("%s.%s must be a string: %w", path, key, err)
	}
	return nil
}

func validateOptionalStringArray(fields map[string]json.RawMessage, key, path string) error {
	value, found := fields[key]
	if !found {
		return nil
	}
	if rawKind(value) != '[' {
		return fmt.Errorf("%s.%s must be an array of strings", path, key)
	}
	var decoded []json.RawMessage
	if err := json.Unmarshal(value, &decoded); err != nil {
		return fmt.Errorf("%s.%s must be an array of strings: %w", path, key, err)
	}
	for _, item := range decoded {
		if rawKind(item) != '"' {
			return fmt.Errorf("%s.%s must be an array of strings", path, key)
		}
	}
	return nil
}

func rawJSONInteger(data json.RawMessage) bool {
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.UseNumber()
	var decoded any
	if err := decoder.Decode(&decoded); err != nil {
		return false
	}
	number, ok := decoded.(json.Number)
	if !ok {
		return false
	}
	value, ok := new(big.Rat).SetString(number.String())
	return ok && value.IsInt()
}
