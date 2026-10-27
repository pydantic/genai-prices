use std::fmt;
use std::sync::Arc;

/// The category of an [`Error`].
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
#[non_exhaustive]
pub enum ErrorKind {
    /// No provider matched the request.
    ProviderNotFound,
    /// No model matched the request.
    ModelNotFound,
    /// The provider has no usage extractor for the requested API flavor.
    ExtractorNotFound,
    /// Usage values are invalid or internally inconsistent.
    InvalidUsage,
    /// Provider data could not be decoded or validated.
    InvalidData,
    /// A provider response did not have the shape its usage extractor expects.
    InvalidResponse,
    /// A regular expression in the provider data exceeded its backtracking limit.
    Match,
}

impl fmt::Display for ErrorKind {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Self::ProviderNotFound => "provider not found",
            Self::ModelNotFound => "model not found",
            Self::ExtractorNotFound => "usage extractor not found",
            Self::InvalidUsage => "invalid usage",
            Self::InvalidData => "invalid provider data",
            Self::InvalidResponse => "invalid response",
            Self::Match => "match failed",
        })
    }
}

/// An error returned while loading provider data, calculating prices or extracting usage.
///
/// Use [`Error::kind`] to decide how to handle it. The message is meant for people and is not part of the
/// stability contract.
///
/// ```
/// use genai_prices::{Calculator, ErrorKind, PriceRequest, Usage};
///
/// let calculator = Calculator::from_json(r#"[{"id": "acme", "name": "Acme", "api_pattern": "acme", "models": []}]"#)?;
/// let usage = Usage::new();
/// let error = calculator.calculate(&PriceRequest::new("no-such-model", &usage).with_provider_id("acme")).unwrap_err();
/// assert_eq!(error.kind(), ErrorKind::ModelNotFound);
/// # Ok::<(), genai_prices::Error>(())
/// ```
#[derive(Debug, Clone)]
pub struct Error {
    kind: ErrorKind,
    message: String,
    source: Option<Arc<dyn std::error::Error + Send + Sync>>,
}

impl Error {
    pub(crate) fn new(kind: ErrorKind, message: impl Into<String>) -> Self {
        Self { kind, message: message.into(), source: None }
    }

    pub(crate) fn with_source(mut self, source: impl std::error::Error + Send + Sync + 'static) -> Self {
        self.source = Some(Arc::new(source));
        self
    }

    /// The category of this error.
    #[must_use]
    pub fn kind(&self) -> ErrorKind {
        self.kind
    }
}

impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{}: {}", self.kind, self.message)
    }
}

impl std::error::Error for Error {
    fn source(&self) -> Option<&(dyn std::error::Error + 'static)> {
        self.source.as_deref().map(|source| source as &(dyn std::error::Error + 'static))
    }
}

/// A specialised [`Result`](std::result::Result) for this crate.
pub type Result<T, E = Error> = std::result::Result<T, E>;

pub(crate) fn validate_number(label: &str, value: f64) -> Result<()> {
    if value.is_finite() && value >= 0.0 {
        Ok(())
    } else {
        Err(Error::new(ErrorKind::InvalidUsage, format!("{label} must be a finite non-negative number")))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn display_and_source() {
        let cases = [
            (ErrorKind::ProviderNotFound, "provider not found: a"),
            (ErrorKind::ModelNotFound, "model not found: a"),
            (ErrorKind::ExtractorNotFound, "usage extractor not found: a"),
            (ErrorKind::InvalidUsage, "invalid usage: a"),
            (ErrorKind::InvalidData, "invalid provider data: a"),
            (ErrorKind::InvalidResponse, "invalid response: a"),
            (ErrorKind::Match, "match failed: a"),
        ];
        for (kind, message) in cases {
            let error = Error::new(kind, "a");
            assert_eq!((error.kind(), error.to_string().as_str()), (kind, message));
            assert!(std::error::Error::source(&error).is_none());
        }
        let cause = serde_json::from_str::<serde_json::Value>("x").unwrap_err();
        let error = Error::new(ErrorKind::InvalidData, "a").with_source(cause);
        assert!(std::error::Error::source(&error).unwrap().to_string().contains("expected value"));
    }
}
