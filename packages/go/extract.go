package genaiprices

import (
	"encoding/json"
	"fmt"
	"net/url"
	"sort"
	"strings"
)

// ExtractUsage extracts usage using the bundled provider data.
func ExtractUsage(request ExtractRequest) (ExtractedUsage, error) {
	return bundledCalculator.ExtractUsage(request)
}

// ExtractUsage extracts usage using this calculator's provider-data snapshot.
func (calculator *Calculator) ExtractUsage(request ExtractRequest) (ExtractedUsage, error) {
	if calculator == nil {
		return ExtractedUsage{}, fmt.Errorf("%w: calculator is nil", ErrInvalidData)
	}
	if request.ProviderID == "" && request.ProviderAPIURL == "" {
		return ExtractedUsage{}, fmt.Errorf("%w: provider ID or provider API URL is required", ErrProviderNotFound)
	}
	if request.ProviderID != "" && request.ProviderAPIURL != "" {
		return ExtractedUsage{}, fmt.Errorf("%w: provider ID and provider API URL are mutually exclusive", ErrInvalidUsage)
	}
	selected, err := findProvider(calculator.providers, "", request.ProviderID, request.ProviderAPIURL)
	if err != nil {
		return ExtractedUsage{}, fmt.Errorf("match provider: %w", err)
	}
	if selected == nil {
		return ExtractedUsage{}, fmt.Errorf(
			"%w: provider_id=%q provider_api_url=%q",
			ErrProviderNotFound,
			request.ProviderID,
			request.ProviderAPIURL,
		)
	}
	if len(selected.Extractors) == 0 {
		return ExtractedUsage{}, fmt.Errorf("%w: no extraction logic for provider %q", ErrExtractorNotFound, selected.ID)
	}
	flavor := request.APIFlavor
	if flavor == "" {
		flavor = "default"
	}
	var extractor *usageExtractor
	for index := range selected.Extractors {
		if selected.Extractors[index].APIFlavor == flavor {
			extractor = &selected.Extractors[index]
			break
		}
	}
	if extractor == nil {
		flavors := make([]string, 0, len(selected.Extractors))
		for _, candidate := range selected.Extractors {
			flavors = append(flavors, candidate.APIFlavor)
		}
		return ExtractedUsage{}, fmt.Errorf(
			"%w: unknown API flavor %q for provider %q; allowed values: %s",
			ErrExtractorNotFound,
			flavor,
			selected.ID,
			strings.Join(flavors, ", "),
		)
	}

	var response any
	if err := json.Unmarshal(request.ResponseJSON, &response); err != nil {
		return ExtractedUsage{}, fmt.Errorf("decode response JSON: %w", err)
	}
	responseMapping, ok := response.(map[string]any)
	if !ok {
		return ExtractedUsage{}, fmt.Errorf("expected response data to be a mapping, got %s", jsonTypeName(response))
	}
	modelValue, found, err := extractPathValue(extractor.ModelPath, responseMapping, false, nil)
	if err != nil {
		return ExtractedUsage{}, err
	}
	modelID := ""
	if found {
		model, ok := modelValue.(string)
		if ok {
			modelID = model
		}
	}
	usageValue, _, err := extractPathValue(extractor.Root, responseMapping, true, nil)
	if err != nil {
		return ExtractedUsage{}, err
	}
	usageMapping, ok := usageValue.(map[string]any)
	if !ok {
		return ExtractedUsage{}, fmt.Errorf(
			"expected `%s` value to be a mapping, got %s",
			dottedPath(extractor.Root),
			jsonTypeName(usageValue),
		)
	}

	usage := Usage{}
	supportedMappings := 0
	unsupportedDestinations := make(map[string]struct{})
	for _, mapping := range extractor.Mappings {
		if !calculator.registry.isReported(mapping.Dest) {
			unsupportedDestinations[string(mapping.Dest)] = struct{}{}
			continue
		}
		supportedMappings++
		value, found, err := extractPathValue(mapping.Path, usageMapping, mapping.Required, extractor.Root)
		if err != nil {
			return ExtractedUsage{}, err
		}
		if !found {
			continue
		}
		number, ok := value.(float64)
		if !ok {
			if mapping.Required {
				return ExtractedUsage{}, fmt.Errorf(
					"expected `%s` value to be a number, got %s",
					dottedPath(appendPath(extractor.Root, mapping.Path...)),
					jsonTypeName(value),
				)
			}
			continue
		}
		if err := validateNumber(string(mapping.Dest), number); err != nil {
			return ExtractedUsage{}, err
		}
		usage[mapping.Dest] += number
	}
	if supportedMappings > 0 && len(usage) == 0 {
		return ExtractedUsage{}, fmt.Errorf("no usage information found at %s", dottedPath(extractor.Root))
	}
	if modelID == "" && selected.ID == "cloudflare" && request.ProviderAPIURL != "" {
		modelID = cloudflareModelFromURL(request.ProviderAPIURL)
	}
	warnings := []string(nil)
	if len(unsupportedDestinations) > 0 {
		destinations := make([]string, 0, len(unsupportedDestinations))
		for destination := range unsupportedDestinations {
			destinations = append(destinations, destination)
		}
		sort.Strings(destinations)
		warnings = []string{
			"Unsupported extractor destination for standard extraction: " + strings.Join(destinations, ", "),
		}
	}
	return ExtractedUsage{Usage: usage, Model: modelID, ProviderID: selected.ID, Warnings: warnings}, nil
}

func extractPathValue(
	path extractPath,
	data any,
	required bool,
	prefix extractPath,
) (any, bool, error) {
	current := data
	traversed := make(extractPath, 0, len(path))
	for index, step := range path {
		traversed = append(traversed, step)
		last := index == len(path)-1
		if step.key != nil {
			mapping, ok := current.(map[string]any)
			if !ok {
				if !required {
					return nil, false, nil
				}
				return nil, false, fmt.Errorf(
					"expected `%s` value to be a mapping, got %s",
					dottedPath(appendPath(prefix, traversed[:len(traversed)-1]...)),
					jsonTypeName(current),
				)
			}
			value, found := mapping[*step.key]
			if !found {
				if !required {
					return nil, false, nil
				}
				return nil, false, fmt.Errorf("missing value at `%s`", dottedPath(appendPath(prefix, traversed...)))
			}
			current = value
			if last {
				return current, true, nil
			}
			continue
		}

		items, ok := current.([]any)
		if !ok {
			if !required {
				return nil, false, nil
			}
			return nil, false, fmt.Errorf(
				"expected `%s` value to be an array, got %s",
				dottedPath(appendPath(prefix, traversed[:len(traversed)-1]...)),
				jsonTypeName(current),
			)
		}
		matched, err := findArrayItem(items, step.arrayMatch)
		if err != nil {
			return nil, false, err
		}
		if matched == nil {
			if !required {
				return nil, false, nil
			}
			return nil, false, fmt.Errorf("unable to find item at `%s`", dottedPath(appendPath(prefix, traversed...)))
		}
		current = matched
	}
	return current, true, nil
}

func findArrayItem(items []any, finder *arrayMatch) (map[string]any, error) {
	for _, item := range items {
		mapping, ok := item.(map[string]any)
		if !ok {
			continue
		}
		field, ok := mapping[finder.Field].(string)
		if !ok {
			continue
		}
		matched, err := finder.Match.matches(field)
		if err != nil {
			return nil, err
		}
		if matched {
			return mapping, nil
		}
	}
	return nil, nil
}

func appendPath(path extractPath, steps ...pathStep) extractPath {
	combined := make(extractPath, 0, len(path)+len(steps))
	combined = append(combined, path...)
	combined = append(combined, steps...)
	return combined
}

func dottedPath(path extractPath) string {
	parts := make([]string, 0, len(path))
	for _, step := range path {
		if step.key != nil {
			parts = append(parts, *step.key)
			continue
		}
		encoded, _ := json.Marshal(step.arrayMatch)
		parts = append(parts, string(encoded))
	}
	return strings.Join(parts, ".")
}

func jsonTypeName(value any) string {
	switch value.(type) {
	case nil:
		return "null"
	case []any:
		return "array"
	case map[string]any:
		return "mapping"
	case string:
		return "string"
	case float64:
		return "number"
	case bool:
		return "boolean"
	default:
		return fmt.Sprintf("%T", value)
	}
}

func cloudflareModelFromURL(value string) string {
	parsed, err := url.Parse(value)
	if err != nil {
		return ""
	}
	_, model, found := strings.Cut(parsed.Path, "/ai/run/")
	if !found {
		return ""
	}
	return model
}
