package genai_prices

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"regexp"
	"sort"
	"strconv"
	"strings"
)

const (
	maxSafeUnitPer = uint64(9_007_199_254_740_991)
	maxUnitCount   = 4096
)

var (
	publicUnitKeyPattern   = regexp.MustCompile(`^[A-Za-z][A-Za-z0-9_]*$`)
	reservedPublicUnitKeys = map[string]struct{}{
		"__proto__": {}, "False": {}, "None": {}, "True": {}, "and": {}, "arguments": {}, "as": {}, "assert": {},
		"async": {}, "await": {}, "break": {}, "case": {}, "catch": {}, "class": {}, "const": {}, "constructor": {},
		"continue": {}, "debugger": {}, "def": {}, "default": {}, "del": {},
		"delete": {}, "do": {}, "elif": {}, "else": {}, "enum": {}, "eval": {}, "except": {}, "export": {},
		"extends": {}, "false": {}, "finally": {}, "for": {}, "from": {}, "function": {}, "global": {}, "if": {},
		"implements": {}, "import": {}, "in": {}, "instanceof": {}, "interface": {}, "is": {}, "lambda": {},
		"let": {}, "new": {}, "nonlocal": {}, "not": {}, "null": {}, "or": {}, "package": {}, "pass": {},
		"private": {}, "protected": {}, "prototype": {}, "public": {}, "raise": {}, "return": {}, "static": {},
		"super": {}, "switch": {}, "this": {}, "throw": {}, "true": {}, "try": {}, "typeof": {}, "var": {},
		"void": {}, "while": {}, "with": {}, "yield": {},
	}
)

func (unit *wireUnitDef) UnmarshalJSON(data []byte) error {
	*unit = wireUnitDef{}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(data, &fields); err != nil {
		return err
	}
	if fields == nil {
		return errors.New("unit must be an object")
	}

	perData, found := fields["per"]
	if !found {
		return errors.New("unit is missing per")
	}
	if err := json.Unmarshal(perData, &unit.Per); err != nil {
		return fmt.Errorf("unit per must be an integer: %w", err)
	}
	dimensionsData, found := fields["dimensions"]
	if !found {
		return errors.New("unit is missing dimensions")
	}
	if err := json.Unmarshal(dimensionsData, &unit.Dimensions); err != nil {
		return fmt.Errorf("unit dimensions must be an object of strings: %w", err)
	}
	if unit.Dimensions == nil {
		return errors.New("unit dimensions must be an object")
	}
	if priceKeyData, found := fields["price_key"]; found {
		if len(trimSpace(priceKeyData)) == 0 || trimSpace(priceKeyData)[0] != '"' {
			return errors.New("unit price_key must be a string")
		}
		if err := json.Unmarshal(priceKeyData, &unit.PriceKey); err != nil {
			return fmt.Errorf("unit price_key must be a string: %w", err)
		}
		if unit.PriceKey == "" {
			return errors.New("unit price key must not be empty")
		}
	}
	return nil
}

func (units *orderedWireUnits) UnmarshalJSON(data []byte) error {
	decoder := json.NewDecoder(bytes.NewReader(data))
	token, err := decoder.Token()
	if err != nil {
		return err
	}
	if delimiter, ok := token.(json.Delim); !ok || delimiter != '{' {
		return errors.New("units must be an object")
	}

	order := make([]UsageKey, 0)
	values := make(map[UsageKey]wireUnitDef)
	seen := make(map[UsageKey]struct{})
	for decoder.More() {
		token, err = decoder.Token()
		if err != nil {
			return err
		}
		key, ok := token.(string)
		if !ok {
			return errors.New("unit usage key must be a string")
		}
		var rawUnit json.RawMessage
		if err := decoder.Decode(&rawUnit); err != nil {
			return err
		}
		var unit wireUnitDef
		if err := json.Unmarshal(rawUnit, &unit); err != nil {
			return fmt.Errorf("unit %q: %w", key, err)
		}
		usageKey := UsageKey(key)
		if _, found := seen[usageKey]; !found {
			order = append(order, usageKey)
			seen[usageKey] = struct{}{}
		}
		values[usageKey] = unit
	}
	if _, err := decoder.Token(); err != nil {
		return err
	}
	units.Order = order
	units.Values = values
	units.CompatibilityWarnings = nil
	return nil
}

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
		unit.dimensions = cloneDimensions(value.dimensions)
		registry.units[key] = &unit
		registry.byPriceKey[unit.priceKey] = &unit
		registry.byDimensions[dimensionKey(unit.dimensions)] = &unit
	}
	unitsByFamily := make(map[string][]*unitDef)
	for _, unit := range registry.units {
		family := unit.dimensions["family"]
		unitsByFamily[family] = append(unitsByFamily[family], unit)
	}
	for key, unit := range registry.units {
		ancestors := make(map[UsageKey]struct{})
		for _, candidate := range unitsByFamily[unit.dimensions["family"]] {
			if candidate != unit && isDimensionSubset(candidate, unit) {
				ancestors[candidate.usageKey] = struct{}{}
			}
		}
		registry.ancestors[key] = ancestors
	}
	return registry
}

func newUntrustedUnitRegistry(wireUnits orderedWireUnits) (*unitRegistry, error) {
	if wireUnits.Values == nil {
		return nil, errors.New("units must be an object")
	}
	if len(wireUnits.Order) != len(wireUnits.Values) {
		return nil, errors.New("unit order must contain every decoded unit exactly once")
	}
	if len(wireUnits.Order) > maxUnitCount {
		return nil, fmt.Errorf("units must contain at most %d entries", maxUnitCount)
	}

	units := make(map[UsageKey]unitDef, len(wireUnits.Values))
	usageByPriceKey := make(map[string]UsageKey, len(wireUnits.Values))
	usageByDimensions := make(map[string]UsageKey, len(wireUnits.Values))
	perByFamily := make(map[string]uint64)
	seen := make(map[UsageKey]struct{}, len(wireUnits.Order))
	for _, usageKey := range wireUnits.Order {
		if _, duplicate := seen[usageKey]; duplicate {
			return nil, fmt.Errorf("duplicate unit order entry %q", usageKey)
		}
		seen[usageKey] = struct{}{}
		wireUnit, found := wireUnits.Values[usageKey]
		if !found {
			return nil, fmt.Errorf("unit order references missing unit %q", usageKey)
		}
		if err := validatePublicUnitKey("usage", string(usageKey)); err != nil {
			return nil, err
		}
		if wireUnit.Per == 0 || wireUnit.Per > maxSafeUnitPer {
			return nil, fmt.Errorf("unit %q per must be an integer from 1 through %d", usageKey, maxSafeUnitPer)
		}
		if wireUnit.Dimensions == nil {
			return nil, fmt.Errorf("unit %q dimensions must be an object", usageKey)
		}
		dimensions := cloneDimensions(wireUnit.Dimensions)
		for key, value := range dimensions {
			if key == "" || value == "" {
				return nil, fmt.Errorf("unit %q dimensions must use non-empty string keys and values", usageKey)
			}
		}
		family, found := dimensions["family"]
		if !found {
			return nil, fmt.Errorf("unit %q is missing the family dimension", usageKey)
		}

		priceKey := wireUnit.PriceKey
		if priceKey == "" {
			priceKey = string(usageKey)
		}
		if err := validatePublicUnitKey("price", priceKey); err != nil {
			return nil, err
		}
		if previous, duplicate := usageByPriceKey[priceKey]; duplicate {
			return nil, fmt.Errorf("units %q and %q use price key %q", previous, usageKey, priceKey)
		}
		usageByPriceKey[priceKey] = usageKey
		dimensionsKey := dimensionKey(dimensions)
		if previous, duplicate := usageByDimensions[dimensionsKey]; duplicate {
			return nil, fmt.Errorf("units %q and %q use identical dimensions", previous, usageKey)
		}
		usageByDimensions[dimensionsKey] = usageKey
		if previous, found := perByFamily[family]; found && previous != wireUnit.Per {
			return nil, fmt.Errorf(
				"unit %q per %d differs from %d for family %q",
				usageKey,
				wireUnit.Per,
				previous,
				family,
			)
		}
		perByFamily[family] = wireUnit.Per
		units[usageKey] = unitDef{priceKey: priceKey, per: float64(wireUnit.Per), dimensions: dimensions}
	}

	if err := validateUnitJoins(units, wireUnits.Order, usageByDimensions); err != nil {
		return nil, err
	}
	return newUnitRegistry(units, wireUnits.Order), nil
}

func validateUnitEvolution(previous, candidate *unitRegistry) error {
	for _, usageKey := range previous.order {
		if candidate.units[usageKey] == nil {
			return fmt.Errorf("removed published unit: %s", usageKey)
		}
	}

	candidateOldOrder := make([]UsageKey, 0, len(previous.order))
	for _, usageKey := range candidate.order {
		if previous.units[usageKey] != nil {
			candidateOldOrder = append(candidateOldOrder, usageKey)
		}
	}
	if !usageKeySlicesEqual(candidateOldOrder, previous.order) {
		return fmt.Errorf("reordered published units: expected %v, got %v", previous.order, candidateOldOrder)
	}
	if len(candidate.order) < len(previous.order) || !usageKeySlicesEqual(candidate.order[:len(previous.order)], previous.order) {
		for _, usageKey := range candidate.order {
			if previous.units[usageKey] == nil {
				return fmt.Errorf("new unit %s must be appended after all published units", usageKey)
			}
		}
		return errors.New("candidate unit order is shorter than the published order")
	}

	for _, usageKey := range previous.order {
		if !unitDefinitionsEqual(previous.units[usageKey], candidate.units[usageKey]) {
			return fmt.Errorf("redefined published unit: %s", usageKey)
		}
	}
	for _, usageKey := range candidate.order[len(previous.order):] {
		newUnit := candidate.units[usageKey]
		for _, oldUsageKey := range previous.order {
			if isDimensionSubset(newUnit, previous.units[oldUsageKey]) {
				return fmt.Errorf("new unit %s is an ancestor or intermediate of published unit %s", usageKey, oldUsageKey)
			}
		}
	}
	return nil
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
		value := dimensions[key]
		builder.WriteString(strconv.Itoa(len(key)))
		builder.WriteByte(':')
		builder.WriteString(key)
		builder.WriteString(strconv.Itoa(len(value)))
		builder.WriteByte(':')
		builder.WriteString(value)
	}
	return builder.String()
}

func cloneDimensions(dimensions map[string]string) map[string]string {
	cloned := make(map[string]string, len(dimensions))
	for key, value := range dimensions {
		cloned[key] = value
	}
	return cloned
}

func usageKeySlicesEqual(left, right []UsageKey) bool {
	if len(left) != len(right) {
		return false
	}
	for index := range left {
		if left[index] != right[index] {
			return false
		}
	}
	return true
}

func unitDefinitionsEqual(left, right *unitDef) bool {
	return left != nil && right != nil && left.priceKey == right.priceKey && left.per == right.per &&
		dimensionKey(left.dimensions) == dimensionKey(right.dimensions)
}

func validatePublicUnitKey(kind, key string) error {
	if !publicUnitKeyPattern.MatchString(key) {
		return fmt.Errorf("unit %s key %q is not a public identifier", kind, key)
	}
	if _, reserved := reservedPublicUnitKeys[key]; reserved {
		return fmt.Errorf("unit %s key %q is reserved", kind, key)
	}
	return nil
}

func validateUnitJoins(
	units map[UsageKey]unitDef,
	order []UsageKey,
	usageByDimensions map[string]UsageKey,
) error {
	orderByFamily := make(map[string][]UsageKey)
	familyOrder := make([]string, 0)
	for _, usageKey := range order {
		family := units[usageKey].dimensions["family"]
		if _, found := orderByFamily[family]; !found {
			familyOrder = append(familyOrder, family)
		}
		orderByFamily[family] = append(orderByFamily[family], usageKey)
	}
	for _, family := range familyOrder {
		familyOrder := orderByFamily[family]
		for leftIndex, leftUsageKey := range familyOrder {
			left := units[leftUsageKey]
			for _, rightUsageKey := range familyOrder[leftIndex+1:] {
				right := units[rightUsageKey]
				if !dimensionsCompatible(left.dimensions, right.dimensions) {
					continue
				}
				joined := cloneDimensions(left.dimensions)
				for key, value := range right.dimensions {
					joined[key] = value
				}
				if _, found := usageByDimensions[dimensionKey(joined)]; !found {
					return fmt.Errorf("missing join unit dimensions between %s and %s", leftUsageKey, rightUsageKey)
				}
			}
		}
	}
	return nil
}

func dimensionsCompatible(left, right map[string]string) bool {
	for key, value := range left {
		if other, found := right[key]; found && other != value {
			return false
		}
	}
	return true
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
