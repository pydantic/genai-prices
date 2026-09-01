package genai_prices

import (
	"fmt"
	"math"
	"sort"
	"strings"
)

type unitDef struct {
	usageKey   UsageKey
	priceKey   string
	per        float64
	dimensions map[string]string
}

type unitRegistry struct {
	units        map[UsageKey]*unitDef
	order        []UsageKey
	byPriceKey   map[string]*unitDef
	byDimensions map[string]*unitDef
	ancestors    map[UsageKey]map[UsageKey]struct{}
}

func newUnitRegistry(units map[UsageKey]unitDef, order []UsageKey) *unitRegistry {
	registry := &unitRegistry{
		units:        make(map[UsageKey]*unitDef, len(units)),
		order:        append([]UsageKey(nil), order...),
		byPriceKey:   make(map[string]*unitDef, len(units)),
		byDimensions: make(map[string]*unitDef, len(units)),
		ancestors:    make(map[UsageKey]map[UsageKey]struct{}, len(units)),
	}
	for key, value := range units {
		unit := value
		unit.usageKey = key
		registry.units[key] = &unit
		registry.byPriceKey[unit.priceKey] = &unit
		registry.byDimensions[dimensionKey(unit.dimensions)] = &unit
	}
	for key, unit := range registry.units {
		ancestors := make(map[UsageKey]struct{})
		for candidateKey, candidate := range registry.units {
			if candidate != unit && isDimensionSubset(candidate, unit) {
				ancestors[candidateKey] = struct{}{}
			}
		}
		registry.ancestors[key] = ancestors
	}
	return registry
}

func (registry *unitRegistry) isReported(key UsageKey) bool {
	_, found := registry.units[key]
	return found && key != UsageRequests
}

func (registry *unitRegistry) findJoin(left, right *unitDef) *unitDef {
	if !isCompatible(left, right) {
		return nil
	}
	dimensions := make(map[string]string, len(left.dimensions)+len(right.dimensions))
	for key, value := range left.dimensions {
		dimensions[key] = value
	}
	for key, value := range right.dimensions {
		dimensions[key] = value
	}
	return registry.byDimensions[dimensionKey(dimensions)]
}

func dimensionKey(dimensions map[string]string) string {
	keys := make([]string, 0, len(dimensions))
	for key := range dimensions {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	var builder strings.Builder
	for _, key := range keys {
		builder.WriteString(key)
		builder.WriteByte('=')
		builder.WriteString(dimensions[key])
		builder.WriteByte(0)
	}
	return builder.String()
}

func isDimensionSubset(ancestor, descendant *unitDef) bool {
	for key, value := range ancestor.dimensions {
		if descendant.dimensions[key] != value {
			return false
		}
	}
	return true
}

func isCompatible(left, right *unitDef) bool {
	for key, value := range left.dimensions {
		if other, found := right.dimensions[key]; found && other != value {
			return false
		}
	}
	return true
}

func validateModelPrice(prices modelPrice, registry *unitRegistry) error {
	pricedUnits := make([]*unitDef, 0, len(prices))
	for priceKey, price := range prices {
		unit := registry.byPriceKey[priceKey]
		if unit == nil {
			continue
		}
		if err := validatePriceValue(priceKey, price); err != nil {
			return err
		}
		pricedUnits = append(pricedUnits, unit)
	}
	priced := make(map[string]struct{}, len(pricedUnits))
	for _, unit := range pricedUnits {
		priced[unit.priceKey] = struct{}{}
	}
	for _, unit := range pricedUnits {
		for ancestorKey := range registry.ancestors[unit.usageKey] {
			ancestor := registry.units[ancestorKey]
			if _, found := priced[ancestor.priceKey]; !found {
				return fmt.Errorf("missing ancestor price key %s for %s", ancestor.priceKey, unit.priceKey)
			}
		}
	}
	for leftIndex, left := range pricedUnits {
		for _, right := range pricedUnits[leftIndex+1:] {
			if !isCompatible(left, right) {
				continue
			}
			join := registry.findJoin(left, right)
			if join == nil {
				return fmt.Errorf("missing registered join unit for %s and %s", left.priceKey, right.priceKey)
			}
			if _, found := priced[join.priceKey]; !found {
				return fmt.Errorf("missing join price key %s for %s and %s", join.priceKey, left.priceKey, right.priceKey)
			}
		}
	}
	return nil
}

func validatePriceValue(key string, price priceValue) error {
	if err := validateFiniteNonNegative(key, price.base); err != nil {
		return err
	}
	if !price.tiered {
		return nil
	}
	for _, tier := range price.tiers {
		if tier.Start < 0 {
			return fmt.Errorf("%s tier start must be non-negative", key)
		}
		if err := validateFiniteNonNegative(key, tier.Price); err != nil {
			return err
		}
	}
	return nil
}

func validateFiniteNonNegative(label string, value float64) error {
	if math.IsNaN(value) || math.IsInf(value, 0) || value < 0 {
		return fmt.Errorf("%s must be a finite non-negative number", label)
	}
	return nil
}

func getUsageValue(usage Usage, key UsageKey, registry *unitRegistry) (float64, error) {
	requested := registry.units[key]
	if requested == nil {
		return 0, fmt.Errorf("%w: unknown unit usage key %s", ErrInvalidUsage, key)
	}
	if !registry.isReported(key) {
		return 0, fmt.Errorf("%w: unsupported usage key for standard pricing: %s", ErrInvalidUsage, key)
	}
	if value, found := usage[key]; found {
		if err := validateNumber(string(key), value); err != nil {
			return 0, err
		}
		return value, nil
	}

	positive := make([]*unitDef, 0, len(usage))
	for reportedKey, value := range usage {
		reported := registry.units[reportedKey]
		if reported == nil || !registry.isReported(reportedKey) {
			continue
		}
		if err := validateNumber(string(reportedKey), value); err != nil {
			return 0, err
		}
		if value <= 0 {
			continue
		}
		positive = append(positive, reported)
		if reportedKey != key {
			if _, found := registry.ancestors[reportedKey][key]; found {
				return 0, fmt.Errorf(
					"%w: missing usage value for %s with positive reported descendant %s",
					ErrInvalidUsage,
					key,
					reportedKey,
				)
			}
		}
	}

	for leftIndex, left := range positive {
		for _, right := range positive[leftIndex+1:] {
			if !isCompatible(left, right) || comparableUnits(registry, left, right) {
				continue
			}
			if registry.findJoin(left, right) == requested {
				return 0, fmt.Errorf(
					"%w: missing usage value for %s with positive reported overlap %s and %s",
					ErrInvalidUsage,
					key,
					left.usageKey,
					right.usageKey,
				)
			}
		}
	}
	return 0, nil
}

func comparableUnits(registry *unitRegistry, left, right *unitDef) bool {
	if left == right {
		return true
	}
	_, leftAncestor := registry.ancestors[right.usageKey][left.usageKey]
	_, rightAncestor := registry.ancestors[left.usageKey][right.usageKey]
	return leftAncestor || rightAncestor
}

func computeLeafValues(keys map[UsageKey]struct{}, usage Usage, registry *unitRegistry) (Usage, error) {
	units := make([]*unitDef, 0, len(keys))
	for key := range keys {
		if unit := registry.units[key]; unit != nil {
			units = append(units, unit)
		}
	}
	sort.Slice(units, func(left, right int) bool {
		leftDimensions := len(units[left].dimensions)
		rightDimensions := len(units[right].dimensions)
		if leftDimensions != rightDimensions {
			return leftDimensions > rightDimensions
		}
		return units[left].usageKey < units[right].usageKey
	})

	leaves := make(Usage, len(units))
	for _, unit := range units {
		value, err := getUsageValue(usage, unit.usageKey, registry)
		if err != nil {
			return nil, err
		}
		descendantTotal := 0.0
		for _, descendant := range units {
			if descendant == unit || !isDimensionSubset(unit, descendant) {
				continue
			}
			leaf, found := leaves[descendant.usageKey]
			if !found {
				return nil, fmt.Errorf("missing computed leaf value for %s", descendant.usageKey)
			}
			descendantTotal += leaf
		}
		leaf := value - descendantTotal
		tolerance := (math.Nextafter(1, 2) - 1) * max(1, math.Abs(value), math.Abs(descendantTotal)) * float64(len(units)+1)
		if leaf < 0 && math.Abs(leaf) <= tolerance {
			leaf = 0
		}
		if leaf < 0 {
			return nil, negativeLeafError(unit, units, usage, value, leaf, registry)
		}
		leaves[unit.usageKey] = leaf
	}
	return leaves, nil
}

func negativeLeafError(
	unit *unitDef,
	pricedUnits []*unitDef,
	usage Usage,
	unitValue float64,
	leafValue float64,
	registry *unitRegistry,
) error {
	type descendantValue struct {
		unit  *unitDef
		value float64
	}
	values := make([]descendantValue, 0)
	for _, descendant := range pricedUnits {
		if descendant == unit || !isDimensionSubset(unit, descendant) {
			continue
		}
		value, err := getUsageValue(usage, descendant.usageKey, registry)
		if err == nil && value > 0 {
			values = append(values, descendantValue{unit: descendant, value: value})
		}
	}
	for _, descendant := range values {
		if descendant.value > unitValue {
			return fmt.Errorf(
				"%w: %s (%g) cannot exceed %s (%g)",
				ErrInvalidUsage,
				descendant.unit.usageKey,
				descendant.value,
				unit.usageKey,
				unitValue,
			)
		}
	}
	keys := make([]string, 0, len(values))
	for _, value := range values {
		keys = append(keys, string(value.unit.usageKey))
	}
	return fmt.Errorf(
		"%w: more-specific usage for %s totals %g, which exceeds %s (%g)",
		ErrInvalidUsage,
		strings.Join(keys, ", "),
		unitValue-leafValue,
		unit.usageKey,
		unitValue,
	)
}
