//! Calendar arithmetic for price constraints, so the crate needs no date-time dependency.

use std::time::{SystemTime, UNIX_EPOCH};

const SECONDS_PER_DAY: i64 = 86_400;

/// A point in time as whole seconds since the Unix epoch plus a sub-second fraction.
#[derive(Debug, Clone, Copy, PartialEq, PartialOrd)]
pub(crate) struct Instant {
    pub(crate) seconds: i64,
    pub(crate) nanos: u32,
}

impl From<SystemTime> for Instant {
    fn from(time: SystemTime) -> Self {
        match time.duration_since(UNIX_EPOCH) {
            Ok(after) => Self { seconds: saturating_seconds(after.as_secs()), nanos: after.subsec_nanos() },
            Err(error) => {
                let before = error.duration();
                let seconds = saturating_seconds(before.as_secs()).saturating_neg();
                match before.subsec_nanos() {
                    0 => Self { seconds, nanos: 0 },
                    nanos => Self { seconds: seconds.saturating_sub(1), nanos: 1_000_000_000 - nanos },
                }
            }
        }
    }
}

impl Instant {
    /// Seconds since midnight UTC, including the fraction.
    pub(crate) fn utc_seconds_of_day(self) -> f64 {
        #[allow(clippy::cast_precision_loss)] // always below 86,400
        let whole = self.seconds.rem_euclid(SECONDS_PER_DAY) as f64;
        whole + f64::from(self.nanos) / 1e9
    }
}

fn saturating_seconds(seconds: u64) -> i64 {
    i64::try_from(seconds).unwrap_or(i64::MAX)
}

/// Parses a `YYYY-MM-DD` date and returns the Unix timestamp of its midnight UTC.
pub(crate) fn parse_date(value: &str) -> Result<i64, String> {
    let invalid = |reason: &str| format!("invalid start-date constraint {value:?}: {reason}");
    let bytes = value.as_bytes();
    if bytes.len() != 10 || bytes[4] != b'-' || bytes[7] != b'-' {
        return Err(invalid("expected YYYY-MM-DD"));
    }
    let year = digits(&bytes[0..4]).ok_or_else(|| invalid("expected YYYY-MM-DD"))?;
    let month = digits(&bytes[5..7]).ok_or_else(|| invalid("expected YYYY-MM-DD"))?;
    let day = digits(&bytes[8..10]).ok_or_else(|| invalid("expected YYYY-MM-DD"))?;
    if year < 1 {
        return Err(invalid("year must be at least 1"));
    }
    if !is_valid_date(year, month, day) {
        return Err(invalid("day or month out of range"));
    }
    Ok(days_from_civil(year, month, day) * SECONDS_PER_DAY)
}

/// Parses an `HH:MM:SS[.fraction](Z|±HH:MM)` time and returns its seconds since midnight UTC.
pub(crate) fn parse_time_of_day(value: &str) -> Result<f64, String> {
    let invalid = || format!("invalid time-of-day constraint {value:?}");
    let bytes = value.as_bytes();
    if bytes.len() < 9 || bytes[2] != b':' || bytes[5] != b':' {
        return Err(invalid());
    }
    let hour = digits(&bytes[0..2]).ok_or_else(invalid)?;
    let minute = digits(&bytes[3..5]).ok_or_else(invalid)?;
    let second = digits(&bytes[6..8]).ok_or_else(invalid)?;
    if hour > 23 || minute > 59 || second > 59 {
        return Err(invalid());
    }
    let mut rest = &value[8..];
    let mut fraction = 0.0;
    if let Some(after_dot) = rest.strip_prefix('.') {
        let end = after_dot.find(|c: char| !c.is_ascii_digit()).unwrap_or(after_dot.len());
        if end == 0 || end > 9 {
            return Err(invalid());
        }
        fraction = format!("0.{}", &after_dot[..end]).parse::<f64>().map_err(|_| invalid())?;
        rest = &after_dot[end..];
    }
    let offset = match rest.as_bytes() {
        b"Z" => 0,
        [sign @ (b'+' | b'-'), h1, h2, b':', m1, m2] => {
            let hours = digits(&[*h1, *h2]).ok_or_else(invalid)?;
            let minutes = digits(&[*m1, *m2]).ok_or_else(invalid)?;
            if hours > 23 || minutes > 59 {
                return Err(invalid());
            }
            let offset = hours * 3_600 + minutes * 60;
            if *sign == b'-' { -offset } else { offset }
        }
        _ => return Err(invalid()),
    };
    let local = hour * 3_600 + minute * 60 + second - offset;
    #[allow(clippy::cast_precision_loss)] // always below 86,400
    let seconds = local.rem_euclid(SECONDS_PER_DAY) as f64;
    Ok(seconds + fraction)
}

/// Whether `year-month-day` names a real day in the proleptic Gregorian calendar.
pub(crate) fn is_valid_date(year: i64, month: i64, day: i64) -> bool {
    let days_in_month = match month {
        1 | 3 | 5 | 7 | 8 | 10 | 12 => 31,
        4 | 6 | 9 | 11 => 30,
        2 if year % 4 == 0 && (year % 100 != 0 || year % 400 == 0) => 29,
        2 => 28,
        _ => return false,
    };
    (1..=days_in_month).contains(&day)
}

/// Days since 1970-01-01 (Howard Hinnant's `days_from_civil`).
fn days_from_civil(year: i64, month: i64, day: i64) -> i64 {
    let year = if month <= 2 { year - 1 } else { year };
    let era = year.div_euclid(400);
    let year_of_era = year - era * 400;
    let day_of_year = (153 * (month + if month > 2 { -3 } else { 9 }) + 2) / 5 + day - 1;
    let day_of_era = year_of_era * 365 + year_of_era / 4 - year_of_era / 100 + day_of_year;
    era * 146_097 + day_of_era - 719_468
}

fn digits(bytes: &[u8]) -> Option<i64> {
    bytes.iter().try_fold(0, |total, byte| byte.is_ascii_digit().then(|| total * 10 + i64::from(byte - b'0')))
}

#[cfg(test)]
mod tests {
    use std::time::Duration;

    use super::*;

    #[test]
    fn dates() {
        assert_eq!(parse_date("1970-01-01"), Ok(0));
        assert_eq!(parse_date("2026-01-01"), Ok(1_767_225_600));
        assert_eq!(parse_date("2024-02-29"), Ok(1_709_164_800));
        assert_eq!(parse_date("0001-01-01"), Ok(-62_135_596_800));
        for invalid in ["0000-01-01", "2025-02-29", "2026-13-01", "2026-1-01", "bad", "2026-01-0x", "+202-01-01"] {
            assert!(parse_date(invalid).is_err(), "{invalid}");
        }
    }

    #[test]
    fn times_of_day() {
        assert_eq!(parse_time_of_day("01:00:00Z"), Ok(3_600.0));
        assert_eq!(parse_time_of_day("23:00:00+01:00"), Ok(79_200.0));
        assert_eq!(parse_time_of_day("00:30:00+01:00"), Ok(84_600.0));
        assert_eq!(parse_time_of_day("23:30:00-01:00"), Ok(1_800.0));
        assert_eq!(parse_time_of_day("12:00:00.5Z"), Ok(43_200.5));
        for invalid in ["bad", "24:00:00Z", "12:00:00", "12:00:00+0100", "12:00:00.Z", "12:60:00Z", "12:00:00+24:00"] {
            assert!(parse_time_of_day(invalid).is_err(), "{invalid}");
        }
    }

    #[test]
    fn instants() {
        let instant = Instant::from(UNIX_EPOCH + Duration::from_millis(86_400_500));
        assert_eq!(instant, Instant { seconds: 86_400, nanos: 500_000_000 });
        assert!((instant.utc_seconds_of_day() - 0.5).abs() < 1e-9);

        let before = Instant::from(UNIX_EPOCH - Duration::from_millis(1_500));
        assert_eq!(before, Instant { seconds: -2, nanos: 500_000_000 });
        assert!((before.utc_seconds_of_day() - 86_398.5).abs() < 1e-9);
        assert_eq!(Instant::from(UNIX_EPOCH - Duration::from_secs(1)), Instant { seconds: -1, nanos: 0 });
    }
}
