//! `Calculator::calculate` allocates only the strings it returns. A counting global allocator checks this.
//! Counts are per thread, so other tests running concurrently do not disturb them.
//!
//! Two paths are deliberately left out: model references that need a compact date rewritten
//! (`-20250807` to `-2025-08-07`), which only runs after an exact lookup has failed, and Groq Whisper
//! requests, whose ten-second billing minimum copies the usage.
#![cfg(feature = "bundled")]
#![allow(unsafe_code)] // the counting allocator; the library itself forbids `unsafe`

use std::alloc::{GlobalAlloc, Layout, System};
use std::cell::Cell;
use std::time::{Duration, UNIX_EPOCH};

use genai_prices::{Calculator, PriceRequest, Usage, UsageKey};

struct CountingAllocator;

thread_local! {
    static ALLOCATIONS: Cell<usize> = const { Cell::new(0) };
}

// SAFETY: defers every operation to `System`, only counting calls on the current thread.
unsafe impl GlobalAlloc for CountingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        ALLOCATIONS.with(|count| count.set(count.get() + 1));
        // SAFETY: forwarded unchanged from the caller.
        unsafe { System.alloc(layout) }
    }

    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        // SAFETY: forwarded unchanged from the caller.
        unsafe { System.dealloc(ptr, layout) }
    }

    unsafe fn realloc(&self, ptr: *mut u8, layout: Layout, new_size: usize) -> *mut u8 {
        ALLOCATIONS.with(|count| count.set(count.get() + 1));
        // SAFETY: forwarded unchanged from the caller.
        unsafe { System.realloc(ptr, layout, new_size) }
    }
}

#[global_allocator]
static ALLOCATOR: CountingAllocator = CountingAllocator;

fn allocations_during(f: impl FnOnce()) -> usize {
    let before = ALLOCATIONS.with(Cell::get);
    f();
    ALLOCATIONS.with(Cell::get) - before
}

#[test]
fn calculate_allocates_only_its_result() {
    let calculator = Calculator::bundled();
    let tokens = Usage::from([
        (UsageKey::INPUT_TOKENS, 300_000.0),
        (UsageKey::CACHE_READ_TOKENS, 100_000.0),
        (UsageKey::OUTPUT_TOKENS, 1_000.0),
    ]);
    // Without the cache-read count, decomposition has to prove the missing value is zero.
    let sparse = Usage::from([(UsageKey::INPUT_TOKENS, 1_000.0)]);
    let october = UNIX_EPOCH + Duration::from_secs(1_791_763_200);
    let requests = [
        ("by provider ID", PriceRequest::new("gpt-5", &tokens).with_provider_id("openai").with_timestamp(october)),
        ("inferred provider", PriceRequest::new("claude-sonnet-5", &tokens).with_timestamp(october)),
        ("by API URL", PriceRequest::new("gpt-5", &tokens).with_provider_api_url("https://api.openai.com/v1")),
        ("tiered price", PriceRequest::new("gpt-5.4", &tokens).with_provider_id("openai").with_timestamp(october)),
        (
            "price variant",
            PriceRequest::new("o3", &tokens)
                .with_provider_id("openai")
                .with_timestamp(october)
                .with_price_context("service_tier", "flex"),
        ),
        ("fallback provider", PriceRequest::new("gpt-5", &tokens).with_provider_id("azure").with_timestamp(october)),
        ("LiteLLM route", PriceRequest::new("openai/gpt-5", &tokens).with_provider_id("litellm")),
        ("missing usage key", PriceRequest::new("gpt-5", &sparse).with_provider_id("openai")),
        ("lookahead regex", PriceRequest::new("gemini-3.8-flash-tts", &tokens).with_provider_id("google")),
        ("lookahead regex, last model", PriceRequest::new("mistral-large-4", &tokens).with_provider_id("mistral")),
    ];
    for (name, request) in &requests {
        // Warm up lazily initialised data and per-thread regex caches.
        calculator.calculate(request).unwrap();
        let count = allocations_during(|| drop(calculator.calculate(request).unwrap()));
        // The result owns its provider and model IDs.
        assert_eq!(count, 2, "{name}");
    }

    // IDs that are not already lowercase are copied once each to fold them.
    let request = PriceRequest::new("GPT-5", &tokens).with_provider_id("OpenAI");
    calculator.calculate(&request).unwrap();
    assert_eq!(allocations_during(|| drop(calculator.calculate(&request).unwrap())), 4);
}
