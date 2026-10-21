#![allow(dead_code)]

use std::time::SystemTime;

use chrono::{NaiveDate, TimeZone, Utc};
use genai_prices::{Calculator, Usage, UsageKey};

pub fn calculator(data: &str) -> Calculator {
    Calculator::from_json(data).unwrap_or_else(|error| panic!("{error}"))
}

pub fn utc(year: i32, month: u32, day: u32, hour: u32, minute: u32, second: u32) -> SystemTime {
    let naive = NaiveDate::from_ymd_opt(year, month, day).unwrap().and_hms_opt(hour, minute, second).unwrap();
    Utc.from_utc_datetime(&naive).into()
}

pub fn date(year: i32, month: u32, day: u32) -> SystemTime {
    utc(year, month, day, 0, 0, 0)
}

pub fn usage<const N: usize>(values: [(UsageKey, f64); N]) -> Usage {
    Usage::from(values)
}

#[track_caller]
pub fn assert_close(actual: f64, expected: f64, tolerance: f64) {
    assert!((actual - expected).abs() <= tolerance, "got {actual}, want {expected}");
}
