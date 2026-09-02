package genai_prices

import (
	"encoding/json"
	"fmt"
	"strings"
	"testing"
)

func TestNewUntrustedUnitRegistrySafeIntegerBoundaries(t *testing.T) {
	for _, value := range []string{"1", "9007199254740991"} {
		t.Run(value, func(t *testing.T) {
			registry, err := unitRegistryFromJSON(`{"events":{"dimensions":{"family":"events"},"per":` + value + `}}`)
			if err != nil {
				t.Fatal(err)
			}
			if registry.units["events"].per != jsonNumberFloat(value) {
				t.Fatalf("got per %g", registry.units["events"].per)
			}
		})
	}
}

func TestNewUntrustedUnitRegistryRejectsMalformedUnits(t *testing.T) {
	tests := []struct {
		name    string
		data    string
		message string
	}{
		{name: "array root", data: `[]`, message: "units must be an object"},
		{name: "null unit", data: `{"events":null}`, message: "unit must be an object"},
		{name: "missing per", data: `{"events":{"dimensions":{"family":"events"}}}`, message: "missing per"},
		{name: "zero per", data: `{"events":{"dimensions":{"family":"events"},"per":0}}`, message: "per must be an integer"},
		{name: "negative per", data: `{"events":{"dimensions":{"family":"events"},"per":-1}}`, message: "per must be an integer"},
		{name: "fractional per", data: `{"events":{"dimensions":{"family":"events"},"per":1.5}}`, message: "per must be an integer"},
		{name: "unsafe per", data: `{"events":{"dimensions":{"family":"events"},"per":9007199254740992}}`, message: "per must be an integer"},
		{name: "missing dimensions", data: `{"events":{"per":1}}`, message: "missing dimensions"},
		{name: "null dimensions", data: `{"events":{"dimensions":null,"per":1}}`, message: "dimensions must be an object"},
		{name: "non-string dimension", data: `{"events":{"dimensions":{"family":3},"per":1}}`, message: "dimensions must be an object of strings"},
		{name: "empty dimension", data: `{"events":{"dimensions":{"family":"events","":"value"},"per":1}}`, message: "non-empty string keys"},
		{name: "missing family", data: `{"events":{"dimensions":{"kind":"event"},"per":1}}`, message: "missing the family dimension"},
		{name: "null price key", data: `{"events":{"dimensions":{"family":"events"},"per":1,"price_key":null}}`, message: "price_key must be a string"},
		{name: "empty price key", data: `{"events":{"dimensions":{"family":"events"},"per":1,"price_key":""}}`, message: "price key"},
		{name: "invalid usage key", data: `{"events-value":{"dimensions":{"family":"events"},"per":1}}`, message: "usage key"},
		{name: "reserved usage key", data: `{"class":{"dimensions":{"family":"events"},"per":1}}`, message: "reserved"},
		{name: "invalid price key", data: `{"events":{"dimensions":{"family":"events"},"per":1,"price_key":"event-price"}}`, message: "price key"},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			_, err := unitRegistryFromJSON(test.data)
			if err == nil || !strings.Contains(err.Error(), test.message) {
				t.Fatalf("got %v, want error containing %q", err, test.message)
			}
		})
	}
}

func TestNewUntrustedUnitRegistryRejectsPythonOnlyReservedPublicKeys(t *testing.T) {
	for _, key := range []string{"False", "None", "True", "and", "as", "assert", "async"} {
		t.Run(key+" usage key", func(t *testing.T) {
			_, err := unitRegistryFromJSON(`{"` + key + `":{"dimensions":{"family":"events"},"per":1}}`)
			if err == nil || !strings.Contains(err.Error(), "reserved") {
				t.Fatalf("got %v, want reserved-key error", err)
			}
		})
		t.Run(key+" price key", func(t *testing.T) {
			_, err := unitRegistryFromJSON(`{"events":{"dimensions":{"family":"events"},"per":1,"price_key":"` + key + `"}}`)
			if err == nil || !strings.Contains(err.Error(), "reserved") {
				t.Fatalf("got %v, want reserved-key error", err)
			}
		})
	}
}

func TestOrderedWireUnitsPreserveOrderAndIgnoreExtensions(t *testing.T) {
	var units orderedWireUnits
	err := json.Unmarshal([]byte(`{
		"alpha":{"dimensions":{"family":"alpha"},"future":true,"per":1},
		"beta":{"dimensions":{"family":"beta"},"per":2,"price_key":"beta_price"}
	}`), &units)
	if err != nil {
		t.Fatal(err)
	}
	registry, err := newUntrustedUnitRegistry(units)
	if err != nil {
		t.Fatal(err)
	}
	if !usageKeySlicesEqual(registry.order, []UsageKey{"alpha", "beta"}) {
		t.Fatalf("unexpected order: %v", registry.order)
	}
	if registry.units["alpha"].priceKey != "alpha" || registry.units["beta"].priceKey != "beta_price" {
		t.Fatalf("unexpected price keys: %#v", registry.units)
	}
	if len(units.CompatibilityWarnings) != 0 {
		t.Fatalf("unexpected warnings: %v", units.CompatibilityWarnings)
	}
}

func TestNewUntrustedUnitRegistryRejectsIdentityFamilyAndJoinConflicts(t *testing.T) {
	tests := []struct {
		name    string
		data    string
		message string
	}{
		{
			name: "duplicate price key",
			data: `{
				"a":{"dimensions":{"family":"a"},"per":1,"price_key":"price"},
				"b":{"dimensions":{"family":"b"},"per":1,"price_key":"price"}
			}`,
			message: "use price key",
		},
		{
			name: "duplicate dimensions",
			data: `{
				"a":{"dimensions":{"family":"events"},"per":1},
				"b":{"dimensions":{"family":"events"},"per":1}
			}`,
			message: "identical dimensions",
		},
		{
			name: "inconsistent family per",
			data: `{
				"a":{"dimensions":{"family":"events","kind":"a"},"per":1},
				"b":{"dimensions":{"family":"events","kind":"b"},"per":2}
			}`,
			message: "differs from",
		},
		{
			name: "missing join",
			data: `{
				"input":{"dimensions":{"direction":"input","family":"events"},"per":1},
				"text":{"dimensions":{"family":"events","modality":"text"},"per":1}
			}`,
			message: "missing join unit dimensions",
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			_, err := unitRegistryFromJSON(test.data)
			if err == nil || !strings.Contains(err.Error(), test.message) {
				t.Fatalf("got %v, want error containing %q", err, test.message)
			}
		})
	}

	_, err := unitRegistryFromJSON(`{
		"input":{"dimensions":{"direction":"input","family":"events"},"per":1},
		"text":{"dimensions":{"family":"events","modality":"text"},"per":1},
		"input_text":{"dimensions":{"direction":"input","family":"events","modality":"text"},"per":1}
	}`)
	if err != nil {
		t.Fatalf("expected closed join registry: %v", err)
	}
}

func TestNewUntrustedUnitRegistryKeepsDelimiterLikeDimensionsDistinct(t *testing.T) {
	_, err := unitRegistryFromJSON(`{
		"left":{"dimensions":{"a=b":"c","family":"events"},"per":1},
		"right":{"dimensions":{"a":"b=c","family":"events"},"per":1},
		"joined":{"dimensions":{"a":"b=c","a=b":"c","family":"events"},"per":1}
	}`)
	if err != nil {
		t.Fatal(err)
	}
}

func TestNewUntrustedUnitRegistryScalesAcrossDisjointFamilies(t *testing.T) {
	const unitCount = 100_000
	wireUnits := orderedWireUnits{
		Order:  make([]UsageKey, 0, unitCount),
		Values: make(map[UsageKey]wireUnitDef, unitCount),
	}
	for index := range unitCount {
		usageKey := UsageKey(fmt.Sprintf("unit_%d", index))
		wireUnits.Order = append(wireUnits.Order, usageKey)
		wireUnits.Values[usageKey] = wireUnitDef{Dimensions: map[string]string{"family": fmt.Sprintf("family_%d", index)}, Per: 1}
	}

	registry, err := newUntrustedUnitRegistry(wireUnits)
	if err != nil {
		t.Fatal(err)
	}
	if len(registry.units) != unitCount {
		t.Fatalf("got %d units, want %d", len(registry.units), unitCount)
	}
}

func TestValidateUnitEvolution(t *testing.T) {
	previous := mustUnitRegistryFromJSON(t, `{
		"base":{"dimensions":{"family":"events"},"per":1},
		"other":{"dimensions":{"family":"other"},"per":2}
	}`)
	accepted := []struct {
		name string
		data string
	}{
		{
			name: "unchanged",
			data: `{
				"base":{"dimensions":{"family":"events"},"per":1},
				"other":{"dimensions":{"family":"other"},"per":2}
			}`,
		},
		{
			name: "descendant and new family",
			data: `{
				"base":{"dimensions":{"family":"events"},"per":1},
				"other":{"dimensions":{"family":"other"},"per":2},
				"child":{"dimensions":{"family":"events","kind":"child"},"per":1},
				"remote":{"dimensions":{"family":"remote"},"per":3}
			}`,
		},
	}
	for _, test := range accepted {
		t.Run("accepts "+test.name, func(t *testing.T) {
			if err := validateUnitEvolution(previous, mustUnitRegistryFromJSON(t, test.data)); err != nil {
				t.Fatal(err)
			}
		})
	}

	rejected := []struct {
		name    string
		data    string
		message string
	}{
		{
			name:    "removal",
			data:    `{"base":{"dimensions":{"family":"events"},"per":1}}`,
			message: "removed published unit: other",
		},
		{
			name: "reorder",
			data: `{
				"other":{"dimensions":{"family":"other"},"per":2},
				"base":{"dimensions":{"family":"events"},"per":1}
			}`,
			message: "reordered published units",
		},
		{
			name: "insertion",
			data: `{
				"base":{"dimensions":{"family":"events"},"per":1},
				"inserted":{"dimensions":{"family":"inserted"},"per":1},
				"other":{"dimensions":{"family":"other"},"per":2}
			}`,
			message: "must be appended",
		},
		{
			name: "redefinition",
			data: `{
				"base":{"dimensions":{"family":"events"},"per":1,"price_key":"changed"},
				"other":{"dimensions":{"family":"other"},"per":2}
			}`,
			message: "redefined published unit: base",
		},
	}
	for _, test := range rejected {
		t.Run("rejects "+test.name, func(t *testing.T) {
			err := validateUnitEvolution(previous, mustUnitRegistryFromJSON(t, test.data))
			if err == nil || !strings.Contains(err.Error(), test.message) {
				t.Fatalf("got %v, want error containing %q", err, test.message)
			}
		})
	}

	oldDescendant := mustUnitRegistryFromJSON(t, `{"child":{"dimensions":{"family":"events","kind":"child"},"per":1}}`)
	candidateWithAncestor := mustUnitRegistryFromJSON(t, `{
		"child":{"dimensions":{"family":"events","kind":"child"},"per":1},
		"ancestor":{"dimensions":{"family":"events"},"per":1}
	}`)
	if err := validateUnitEvolution(oldDescendant, candidateWithAncestor); err == nil || !strings.Contains(err.Error(), "ancestor or intermediate") {
		t.Fatalf("got %v", err)
	}
}

func TestValidateUnitEvolutionAllowsAppendedIntersectionWithJoin(t *testing.T) {
	previous := mustUnitRegistryFromJSON(t, `{"input":{"dimensions":{"direction":"input","family":"events"},"per":1}}`)
	candidate := mustUnitRegistryFromJSON(t, `{
		"input":{"dimensions":{"direction":"input","family":"events"},"per":1},
		"text":{"dimensions":{"family":"events","modality":"text"},"per":1},
		"input_text":{"dimensions":{"direction":"input","family":"events","modality":"text"},"per":1}
	}`)
	if err := validateUnitEvolution(previous, candidate); err != nil {
		t.Fatal(err)
	}
}

func TestUnitRegistryConstructionCopiesInput(t *testing.T) {
	dimensions := map[string]string{"family": "events"}
	order := []UsageKey{"events"}
	wire := orderedWireUnits{
		Order: order,
		Values: map[UsageKey]wireUnitDef{
			"events": {Dimensions: dimensions, Per: 1},
		},
	}
	registry, err := newUntrustedUnitRegistry(wire)
	if err != nil {
		t.Fatal(err)
	}
	dimensions["family"] = "mutated"
	order[0] = "mutated"
	wire.Values["events"] = wireUnitDef{Dimensions: map[string]string{"family": "mutated"}, Per: 2}
	if registry.order[0] != "events" || registry.units["events"].dimensions["family"] != "events" || registry.units["events"].per != 1 {
		t.Fatalf("registry retained caller-owned data: %#v", registry)
	}
}

func TestOrderedWireUnitsUsePostParseDuplicateValues(t *testing.T) {
	registry, err := unitRegistryFromJSON(`{
		"events":{"dimensions":{"family":"events"},"per":1,"per":2},
		"events":{"dimensions":{"family":"events"},"per":3}
	}`)
	if err != nil {
		t.Fatal(err)
	}
	if len(registry.order) != 1 || registry.units["events"].per != 3 {
		t.Fatalf("unexpected post-parse duplicate result: order=%v unit=%#v", registry.order, registry.units["events"])
	}
}

func unitRegistryFromJSON(data string) (*unitRegistry, error) {
	var units orderedWireUnits
	if err := json.Unmarshal([]byte(data), &units); err != nil {
		return nil, err
	}
	return newUntrustedUnitRegistry(units)
}

func mustUnitRegistryFromJSON(t *testing.T, data string) *unitRegistry {
	t.Helper()
	registry, err := unitRegistryFromJSON(data)
	if err != nil {
		t.Fatal(err)
	}
	return registry
}

func jsonNumberFloat(value string) float64 {
	var decoded float64
	if err := json.Unmarshal([]byte(value), &decoded); err != nil {
		panic(err)
	}
	return decoded
}
