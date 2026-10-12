package genai_prices

import (
	"encoding/json"
	"fmt"
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

func resolvePriceVariants(model *model, timestamp time.Time, context map[string]string) (modelPrice, []string) {
	standard := activeModelPrice(model, timestamp)
	if len(context) == 0 {
		return standard, nil
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
	if !matched {
		return resolved, []string{fmt.Sprintf("No price variant matched for model '%s'; using standard prices", model.ID)}
	}
	return resolved, nil
}
