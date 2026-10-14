package genai_prices

import (
	"encoding/json"
	"fmt"
	"reflect"
	"time"
)

type priceVariant struct {
	When       map[string]string `json:"when"`
	Prices     modelPrice        `json:"prices"`
	Constraint *priceConstraint  `json:"constraint"`
}

func (variant *priceVariant) UnmarshalJSON(data []byte) error {
	var raw struct {
		When       map[string]json.RawMessage `json:"when"`
		Prices     map[string]json.RawMessage `json:"prices"`
		Constraint *priceConstraint           `json:"constraint"`
	}
	if err := json.Unmarshal(data, &raw); err != nil {
		return err
	}
	if len(raw.When) == 0 || raw.Prices == nil {
		return fmt.Errorf("price variant must contain when and prices")
	}
	variant.When = make(map[string]string, len(raw.When))
	for key, value := range raw.When {
		if len(value) == 0 || value[0] != '"' {
			return fmt.Errorf("price variant when values must be strings")
		}
		var text string
		if err := json.Unmarshal(value, &text); err != nil {
			return err
		}
		variant.When[key] = text
	}
	variant.Prices = make(modelPrice, len(raw.Prices))
	for key, value := range raw.Prices {
		if string(trimSpace(value)) == "null" {
			continue
		}
		var price priceValue
		if err := json.Unmarshal(value, &price); err != nil {
			return err
		}
		variant.Prices[key] = price
	}
	variant.Constraint = raw.Constraint
	return nil
}

func resolvePriceVariants(model *model, provider *provider, timestamp time.Time, context map[string]string) (modelPrice, []string) {
	standard := activeModelPrice(model, timestamp)
	if len(context) == 0 {
		return standard, nil
	}
	ownsModel := false
	for index := range provider.Models {
		if model == &provider.Models[index] {
			ownsModel = true
			break
		}
	}
	resolved := make(modelPrice, len(standard))
	for key, price := range standard {
		resolved[key] = price
	}
	overridden := make(map[string]bool)
	matched := false
	for _, variant := range model.PriceVariants {
		if !variant.Constraint.active(timestamp) {
			continue
		}
		matches := true
		for key, value := range variant.When {
			actual, found := context[key]
			if !found || actual != value {
				matches = false
				break
			}
		}
		if !matches {
			continue
		}
		matched = true
		for key, price := range variant.Prices {
			if !overridden[key] {
				resolved[key] = price
				overridden[key] = true
			}
		}
	}
	var warnings []string
	// A context none of the variants condition on can't change this model's price, so it isn't worth a warning.
	if !matched && usesContextKey(model, context) {
		warnings = append(warnings, fmt.Sprintf("No price variant matched for model '%s'; using standard prices", model.ID))
	}
	if !ownsModel {
		// Another provider's variants are never applied; warn only when they would have changed the price.
		if !reflect.DeepEqual(resolved, standard) {
			warnings = append(warnings, fmt.Sprintf("No price variant matched for provider '%s' model '%s'; using standard prices", provider.ID, model.ID))
		}
		return standard, warnings
	}
	return resolved, warnings
}

func usesContextKey(model *model, context map[string]string) bool {
	for _, variant := range model.PriceVariants {
		for key := range variant.When {
			if _, found := context[key]; found {
				return true
			}
		}
	}
	return false
}
