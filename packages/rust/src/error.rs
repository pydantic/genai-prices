use std::fmt;

/// Errors returned while loading provider data, calculating prices or extracting usage.
///
/// Every variant carries a human-readable description. Match on the variant to decide how to handle
/// the failure; the message text is not part of the stability contract.
#[derive(Debug, Clone, PartialEq, Eq)]
#[non_exhaustive]
pub enum Error {
    /// No provider matched the request.
    ProviderNotFound(String),
    /// No model matched the request.
    ModelNotFound(String),
    /// The provider has no usage extractor for the requested API flavor.
    ExtractorNotFound(String),
    /// Usage values are invalid or internally inconsistent.
    InvalidUsage(String),
    /// Provider data could not be decoded or validated.
    InvalidData(String),
    /// A provider response did not have the shape its usage extractor expects.
    InvalidResponse(String),
    /// A regular expression in the provider data exceeded its backtracking limit.
    Match(String),
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let (kind, message) = match self {
            Self::ProviderNotFound(message) => ("provider not found", message),
            Self::ModelNotFound(message) => ("model not found", message),
            Self::ExtractorNotFound(message) => ("usage extractor not found", message),
            Self::InvalidUsage(message) => ("invalid usage", message),
            Self::InvalidData(message) => ("invalid provider data", message),
            Self::InvalidResponse(message) => ("invalid response", message),
            Self::Match(message) => ("match failed", message),
        };
        write!(f, "{kind}: {message}")
    }
}

impl std::error::Error for Error {}

/// A specialised [`Result`](std::result::Result) for this crate.
pub type Result<T, E = Error> = std::result::Result<T, E>;

pub(crate) fn validate_number(label: &str, value: f64) -> Result<()> {
    if value.is_finite() && value >= 0.0 {
        Ok(())
    } else {
        Err(Error::InvalidUsage(format!("{label} must be a finite non-negative number")))
    }
}
