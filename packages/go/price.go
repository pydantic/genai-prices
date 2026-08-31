package genai_prices

import (
	"fmt"
	"sort"
	"time"
)

func activeModelPrice(model *model, timestamp time.Time) modelPrice {
	if model.Prices.conditional == nil {
		return model.Prices.direct
	}
	for index := len(model.Prices.conditional) - 1; index >= 0; index-- {
		candidate := model.Prices.conditional[index]
		constraint := candidate.Constraint
		if constraint == nil {
			return candidate.Prices
		}
		if constraint.StartDate != "" {
			if !timestamp.Before(constraint.date) {
				return candidate.Prices
			}
			continue
		}
		utc := timestamp.UTC()
		seconds := float64(utc.Hour()*3600+utc.Minute()*60+utc.Second()) + float64(utc.Nanosecond())/1e9
		if constraint.end < constraint.start {
			if seconds >= constraint.start || seconds < constraint.end {
				return candidate.Prices
			}
		} else if seconds >= constraint.start && seconds < constraint.end {
			return candidate.Prices
		}
	}
	return model.Prices.conditional[0].Prices
}

func calculateModelPrice(
	usage Usage,
	prices modelPrice,
	registry *unitRegistry,
) (inputPrice, outputPrice, totalPrice float64, err error) {
	type resolvedPrice struct {
		price priceValue
		unit  *unitDef
	}
	resolved := make([]resolvedPrice, 0, len(prices))
	keys := make(map[UsageKey]struct{}, len(prices))
	hasTiered := false
	hasRequests := false
	priceKeys := make([]string, 0, len(prices))
	for key := range prices {
		priceKeys = append(priceKeys, key)
	}
	sort.Strings(priceKeys)
	for _, key := range priceKeys {
		unit := registry.byPriceKey[key]
		if unit == nil {
			continue
		}
		price := prices[key]
		resolved = append(resolved, resolvedPrice{price: price, unit: unit})
		hasTiered = hasTiered || price.tiered
		if unit.usageKey == UsageRequests {
			hasRequests = true
		} else {
			keys[unit.usageKey] = struct{}{}
		}
	}

	totalInputTokens := 0.0
	if hasTiered {
		totalInputTokens, err = getUsageValue(usage, UsageInputTokens, registry)
		if err != nil {
			return 0, 0, 0, err
		}
	}
	leaves, err := computeLeafValues(keys, usage, registry)
	if err != nil {
		return 0, 0, 0, err
	}
	if hasRequests {
		leaves[UsageRequests] = 1
	}
	for _, item := range resolved {
		count := leaves[item.unit.usageKey]
		price := item.price.base
		if item.price.tiered && count > 0 {
			for _, tier := range item.price.tiers {
				if totalInputTokens > float64(tier.Start) {
					price = tier.Price
				}
			}
		}
		unitPrice := price * count / item.unit.per
		if err := validateNumber("calculated unit price", unitPrice); err != nil {
			return 0, 0, 0, err
		}
		switch item.unit.dimensions["direction"] {
		case "input":
			inputPrice += unitPrice
			if err := validateNumber("calculated input price", inputPrice); err != nil {
				return 0, 0, 0, err
			}
		case "output":
			outputPrice += unitPrice
			if err := validateNumber("calculated output price", outputPrice); err != nil {
				return 0, 0, 0, err
			}
		default:
			totalPrice += unitPrice
			if err := validateNumber("calculated total price", totalPrice); err != nil {
				return 0, 0, 0, err
			}
		}
	}
	totalPrice += inputPrice + outputPrice
	if err := validateNumber("calculated total price", totalPrice); err != nil {
		return 0, 0, 0, err
	}
	return inputPrice, outputPrice, totalPrice, nil
}

func parseConstraint(constraint *priceConstraint) error {
	switch {
	case constraint.StartDate != "" && constraint.StartTime == "" && constraint.EndTime == "":
		date, err := time.Parse("2006-01-02", constraint.StartDate)
		if err != nil {
			return fmt.Errorf("invalid start-date constraint %q: %w", constraint.StartDate, err)
		}
		if date.Year() < 1 {
			return fmt.Errorf("invalid start-date constraint %q: year must be at least 1", constraint.StartDate)
		}
		constraint.date = date
		return nil
	case constraint.StartDate == "" && constraint.StartTime != "" && constraint.EndTime != "":
		start, err := utcTimeOfDaySeconds(constraint.StartTime)
		if err != nil {
			return err
		}
		end, err := utcTimeOfDaySeconds(constraint.EndTime)
		if err != nil {
			return err
		}
		constraint.start = start
		constraint.end = end
		return nil
	default:
		return fmt.Errorf("expected a start-date or time-of-day price constraint")
	}
}

func utcTimeOfDaySeconds(value string) (float64, error) {
	parsed, err := time.Parse("15:04:05.999999999Z07:00", value)
	if err != nil {
		return 0, fmt.Errorf("invalid time-of-day constraint %q: %w", value, err)
	}
	_, offset := parsed.Zone()
	local := float64(parsed.Hour()*3600+parsed.Minute()*60+parsed.Second()) + float64(parsed.Nanosecond())/1e9
	seconds := local - float64(offset)
	for seconds < 0 {
		seconds += 86400
	}
	for seconds >= 86400 {
		seconds -= 86400
	}
	return seconds, nil
}
