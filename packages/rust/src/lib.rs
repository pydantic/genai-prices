#![doc = include_str!("../README.md")]

mod calculator;
#[rustfmt::skip]
mod data_units;
mod decode;
mod error;
mod extract;
mod matching;
mod model;
mod request;
mod time;
mod units;
mod usage;

pub use calculator::{Calculator, calculate};
pub use error::{Error, Result};
pub use extract::extract_usage;
pub use request::{ExtractRequest, ExtractedUsage, PriceCalculation, PriceRequest};
pub use usage::{Usage, UsageKey};

/// The current v2 provider-data feed, for [`Calculator::from_json`].
pub const REMOTE_DATA_URL: &str =
    "https://raw.githubusercontent.com/pydantic/genai-prices/main/prices/new_data/v2/data.json";
