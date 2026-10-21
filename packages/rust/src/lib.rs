#![cfg_attr(feature = "bundled", doc = include_str!("../README.md"))]
#![cfg_attr(
    not(feature = "bundled"),
    doc = "Calculate the price of generative AI API calls. Enable the default `bundled` feature for the \
           embedded price data and the README examples; without it, load data with `Calculator::from_json`."
)]
#![cfg_attr(docsrs, feature(doc_cfg))]

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

pub use calculator::Calculator;
#[cfg(feature = "bundled")]
pub use calculator::calculate;
pub use error::{Error, ErrorKind, Result};
#[cfg(feature = "bundled")]
pub use extract::extract_usage;
pub use request::{ExtractRequest, ExtractedUsage, PriceCalculation, PriceRequest};
pub use usage::{IntoIter, Iter, Usage, UsageKey};

/// The current v2 provider-data feed, for [`Calculator::from_json`].
pub const REMOTE_DATA_URL: &str =
    "https://raw.githubusercontent.com/pydantic/genai-prices/main/prices/new_data/v2/data.json";
