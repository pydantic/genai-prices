package genai_prices

import (
	"fmt"
	"regexp"
	"strconv"
	"strings"
	"time"
)

var compactDatePattern = regexp.MustCompile(`-(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])([-:]|$)`)

func findProviderByID(providers []*provider, providerID string) (*provider, error) {
	normalized := strings.ToLower(strings.TrimSpace(providerID))
	for _, provider := range providers {
		if provider.ID == normalized {
			return provider, nil
		}
	}
	for _, provider := range providers {
		if provider.ProviderMatch == nil {
			continue
		}
		matched, err := provider.ProviderMatch.matches(normalized)
		if err != nil {
			return nil, err
		}
		if matched {
			return provider, nil
		}
	}
	return nil, nil
}

func findProvider(
	providers []*provider,
	modelID string,
	providerID string,
	providerAPIURL string,
) (*provider, error) {
	if providerID != "" {
		provider, err := findProviderByID(providers, providerID)
		if err != nil || provider != nil || !strings.EqualFold(strings.TrimSpace(providerID), "litellm") {
			return provider, err
		}
	}
	if providerAPIURL != "" {
		for _, provider := range providers {
			matched, err := provider.apiRegex.MatchString(providerAPIURL)
			if err != nil {
				return nil, err
			}
			if matched {
				return provider, nil
			}
		}
		return nil, nil
	}
	if modelID != "" {
		for _, provider := range providers {
			if provider.ModelMatch == nil {
				continue
			}
			matched, err := provider.ModelMatch.matches(modelID)
			if err != nil {
				return nil, err
			}
			if matched {
				return provider, nil
			}
		}
	}
	return nil, nil
}

func findModel(providers []*provider, selected *provider, modelID string) (*model, error) {
	matched, err := findModelDirect(providers, selected, modelID, true)
	if err != nil || matched != nil {
		return matched, err
	}
	normalized := normalizeCompactDatedRef(modelID)
	if normalized == modelID {
		return nil, nil
	}
	return findModelDirect(providers, selected, normalized, true)
}

func findModelDirect(providers []*provider, selected *provider, modelID string, allowFallback bool) (*model, error) {
	for index := range selected.Models {
		matched, err := selected.Models[index].Match.matches(modelID)
		if err != nil {
			return nil, err
		}
		if matched {
			return &selected.Models[index], nil
		}
	}
	if allowFallback {
		for _, fallbackID := range selected.FallbackModelProviders {
			for _, fallback := range providers {
				if fallback.ID != fallbackID {
					continue
				}
				matched, err := findModelDirect(providers, fallback, modelID, false)
				if err != nil || matched != nil {
					return matched, err
				}
			}
		}
	}
	return nil, nil
}

func normalizeCompactDatedRef(modelID string) string {
	indices := compactDatePattern.FindAllStringSubmatchIndex(modelID, -1)
	if len(indices) == 0 {
		return modelID
	}
	var builder strings.Builder
	last := 0
	for _, index := range indices {
		year, _ := strconv.Atoi(modelID[index[2]:index[3]])
		month, _ := strconv.Atoi(modelID[index[4]:index[5]])
		day, _ := strconv.Atoi(modelID[index[6]:index[7]])
		date := time.Date(year, time.Month(month), day, 0, 0, 0, 0, time.UTC)
		if date.Year() != year || int(date.Month()) != month || date.Day() != day {
			continue
		}
		builder.WriteString(modelID[last:index[0]])
		_, _ = fmt.Fprintf(&builder, "-%04d-%02d-%02d%s", year, month, day, modelID[index[8]:index[9]])
		last = index[1]
	}
	if last == 0 {
		return modelID
	}
	builder.WriteString(modelID[last:])
	return builder.String()
}
