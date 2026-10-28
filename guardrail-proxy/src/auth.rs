use hmac::{Hmac, Mac};
use sha2::Sha256;
use std::{
    collections::HashMap,
    sync::Mutex,
    time::{SystemTime, UNIX_EPOCH},
};

type HmacSha256 = Hmac<Sha256>;

const MAX_CLOCK_SKEW_SECS: u64 = 300;
const MAX_NONCE_ENTRIES: usize = 100_000;
const MIN_KEY_BYTES: usize = 32;

#[derive(Debug, PartialEq, Eq)]
pub enum AuthError {
    MissingHeader,
    InvalidHeader,
    InvalidTimestamp,
    TimestampOutsideWindow,
    InvalidSignature,
    Replay,
    ReplayCacheUnavailable,
    ReplayCacheFull,
}

pub struct HmacAuthenticator {
    key: Vec<u8>,
    seen_nonces: Mutex<HashMap<String, u64>>,
}

impl HmacAuthenticator {
    pub fn new(key: Vec<u8>) -> Result<Self, &'static str> {
        if key.len() < MIN_KEY_BYTES {
            return Err("SENTINEL_HMAC_KEY must contain at least 32 bytes");
        }
        Ok(Self { key, seen_nonces: Mutex::new(HashMap::new()) })
    }

    /// Verify HMAC-SHA256 over: ASCII timestamp + LF + nonce + LF + raw body.
    /// The signature header is 64 lowercase/uppercase hexadecimal characters.
    /// Replay state is in-memory and therefore only protects this process lifetime.
    pub fn verify(&self, timestamp: &str, nonce: &str, signature_hex: &str, body: &[u8], now: u64) -> Result<(), AuthError> {
        if timestamp.is_empty() || timestamp.len() > 12 || !timestamp.bytes().all(|b| b.is_ascii_digit()) {
            return Err(AuthError::InvalidTimestamp);
        }
        let ts: u64 = timestamp.parse().map_err(|_| AuthError::InvalidTimestamp)?;
        if ts.to_string() != timestamp {
            return Err(AuthError::InvalidTimestamp);
        }
        if now.abs_diff(ts) > MAX_CLOCK_SKEW_SECS {
            return Err(AuthError::TimestampOutsideWindow);
        }
        if nonce.len() < 16 || nonce.len() > 128 ||
            !nonce.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-') {
            return Err(AuthError::InvalidHeader);
        }
        if signature_hex.len() != 64 || !signature_hex.bytes().all(|b| b.is_ascii_hexdigit()) {
            return Err(AuthError::InvalidSignature);
        }
        let signature = hex::decode(signature_hex).map_err(|_| AuthError::InvalidSignature)?;
        let mut mac = HmacSha256::new_from_slice(&self.key).map_err(|_| AuthError::InvalidSignature)?;
        mac.update(timestamp.as_bytes());
        mac.update(b"\n");
        mac.update(nonce.as_bytes());
        mac.update(b"\n");
        mac.update(body);
        // HMAC's verify_slice performs constant-time tag comparison.
        mac.verify_slice(&signature).map_err(|_| AuthError::InvalidSignature)?;

        let mut seen = self.seen_nonces.lock().map_err(|_| AuthError::ReplayCacheUnavailable)?;
        seen.retain(|_, expires_at| *expires_at >= now);
        if seen.contains_key(nonce) {
            return Err(AuthError::Replay);
        }
        if seen.len() >= MAX_NONCE_ENTRIES {
            return Err(AuthError::ReplayCacheFull);
        }
        seen.insert(nonce.to_owned(), ts.saturating_add(MAX_CLOCK_SKEW_SECS));
        Ok(())
    }
}

pub fn unix_time_seconds() -> Result<u64, ()> {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|d| d.as_secs()).map_err(|_| ())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn signed(auth_key: &[u8], ts: &str, nonce: &str, body: &[u8]) -> String {
        let mut mac = HmacSha256::new_from_slice(auth_key).unwrap();
        mac.update(ts.as_bytes());
        mac.update(b"\n");
        mac.update(nonce.as_bytes());
        mac.update(b"\n");
        mac.update(body);
        hex::encode(mac.finalize().into_bytes())
    }

    #[test]
    fn accepts_valid_mac_once_and_rejects_replay() {
        let key = b"0123456789abcdef0123456789abcdef".to_vec();
        let auth = HmacAuthenticator::new(key.clone()).unwrap();
        let nonce = "nonce_1234567890";
        let sig = signed(&key, "1000", nonce, br#"{"prompt":"hello"}"#);
        assert_eq!(auth.verify("1000", nonce, &sig, br#"{"prompt":"hello"}"#, 1000), Ok(()));
        assert_eq!(auth.verify("1000", nonce, &sig, br#"{"prompt":"hello"}"#, 1000), Err(AuthError::Replay));
    }

    #[test]
    fn rejects_wrong_body_and_stale_timestamp() {
        let key = b"0123456789abcdef0123456789abcdef".to_vec();
        let auth = HmacAuthenticator::new(key.clone()).unwrap();
        let nonce = "nonce_1234567890";
        let sig = signed(&key, "1000", nonce, b"original");
        assert_eq!(auth.verify("1000", nonce, &sig, b"changed", 1000), Err(AuthError::InvalidSignature));
        assert_eq!(auth.verify("1000", nonce, &sig, b"original", 1401), Err(AuthError::TimestampOutsideWindow));
    }

    #[test]
    fn rejects_short_key() {
        assert!(HmacAuthenticator::new(vec![0; MIN_KEY_BYTES - 1]).is_err());
    }
}
