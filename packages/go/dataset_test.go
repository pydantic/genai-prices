package genaiprices_test

import (
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"testing"
	"time"

	genaiprices "github.com/pydantic/genai-prices/packages/go"
)

type datasetRow struct {
	Body      json.RawMessage    `json:"body"`
	Extracted []datasetExtracted `json:"extracted"`
	Model     *string            `json:"model"`
}

type datasetExtracted struct {
	Extractors []datasetExtractor `json:"extractors"`
	Usage      genaiprices.Usage  `json:"usage"`
}

type datasetExtractor struct {
	APIFlavor   string  `json:"api_flavor"`
	InputPrice  *string `json:"input_price"`
	OutputPrice *string `json:"output_price"`
	ProviderID  string  `json:"provider_id"`
	TotalPrice  *string `json:"total_price"`
}

func TestDataset(t *testing.T) {
	_, filename, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("unable to locate dataset test")
	}
	data, err := os.ReadFile(filepath.Join(filepath.Dir(filename), "..", "..", "tests", "dataset", "usages.json"))
	if err != nil {
		t.Fatal(err)
	}
	var rows []datasetRow
	if err := json.Unmarshal(data, &rows); err != nil {
		t.Fatal(err)
	}
	for rowIndex, row := range rows {
		t.Run(strconv.Itoa(rowIndex+1), func(t *testing.T) {
			for _, expected := range row.Extracted {
				for _, extractor := range expected.Extractors {
					actual, err := genaiprices.ExtractUsage(genaiprices.ExtractRequest{
						ResponseJSON: row.Body,
						ProviderID:   extractor.ProviderID,
						APIFlavor:    extractor.APIFlavor,
					})
					if err != nil {
						t.Fatalf("extract %s/%s: %v", extractor.ProviderID, extractor.APIFlavor, err)
					}
					expectedModel := ""
					if row.Model != nil {
						expectedModel = *row.Model
					}
					if actual.Model != expectedModel {
						t.Errorf(
							"extract %s/%s model: got %q, want %q",
							extractor.ProviderID,
							extractor.APIFlavor,
							actual.Model,
							expectedModel,
						)
					}
					assertUsage(t, actual.Usage, expected.Usage)
					if actual.Model == "" {
						continue
					}
					calculation, err := genaiprices.Calculate(genaiprices.PriceRequest{
						Usage:      actual.Usage,
						Model:      actual.Model,
						ProviderID: extractor.ProviderID,
						Timestamp:  time.Date(2025, 11, 6, 12, 0, 0, 0, time.UTC),
					})
					if err != nil {
						if errors.Is(err, genaiprices.ErrModelNotFound) && extractor.InputPrice == nil && extractor.OutputPrice == nil {
							continue
						}
						t.Fatalf("calculate %s/%s: %v", extractor.ProviderID, extractor.APIFlavor, err)
					}
					assertPrice(t, "input", calculation.InputPrice, extractor.InputPrice)
					assertPrice(t, "output", calculation.OutputPrice, extractor.OutputPrice)
					if extractor.TotalPrice != nil {
						assertPrice(t, "total", calculation.TotalPrice, extractor.TotalPrice)
					}
				}
			}
		})
	}
}

func assertUsage(t *testing.T, actual, expected genaiprices.Usage) {
	t.Helper()
	for key, expectedValue := range expected {
		actualValue, found := actual[key]
		if !found || math.Abs(actualValue-expectedValue) > 1e-12 {
			t.Errorf("usage %s: got %g, want %g", key, actualValue, expectedValue)
		}
	}
}

func assertPrice(t *testing.T, label string, actual float64, expected *string) {
	t.Helper()
	if expected == nil {
		t.Errorf("%s price unexpectedly calculated as %g", label, actual)
		return
	}
	expectedValue, err := strconv.ParseFloat(*expected, 64)
	if err != nil {
		t.Fatal(fmt.Errorf("parse expected %s price: %w", label, err))
	}
	if math.Abs(actual-expectedValue) > 5e-9 {
		t.Errorf("%s price: got %.12g, want %.12g", label, actual, expectedValue)
	}
}
