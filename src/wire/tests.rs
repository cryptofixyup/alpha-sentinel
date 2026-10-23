#[cfg(test)]
mod tests {
    use super::wire::VersionedTelemetryFrame;

    #[test]
    fn test_canonical_golden_vector_decoding() {
        let hex_vector = concat!(
            "6500000000000000",
            "15cd853dfe9c9717",
            "efcdab1032547698",
            "cdcccc3dcdcc4cbe",
            "9a99993ecdccccbe",
            "0000003f9a9919bf",
            "0000603fd4c3b2a1",
            "7f5edcb1",
            "53410101",
        );

        assert_eq!(hex_vector.len(), 128);

        let bytes = hex::decode(hex_vector).expect("Failed to decode canonical hex vector");
        assert_eq!(bytes.len(), 64);

        let decoded = VersionedTelemetryFrame::decode_from_wire(&bytes)
            .expect("Canonical golden vector failed validation");

        assert_eq!(decoded.sequence_id, 101);
        assert_eq!(decoded.timestamp_ns, 1_700_000_000_123_456_789);
        assert_eq!(decoded.device_id_hash, 0x9876543210ABCDEF);
        assert_eq!(
            decoded.signal_metrics,
            [0.1f32, -0.2f32, 0.3f32, -0.4f32, 0.5f32, -0.6f32]
        );
        assert_eq!(decoded.anomaly_score, 0.875f32);
        assert_eq!(decoded.nonce, 0xA1B2C3D4);
        assert_eq!(decoded.checksum, 0xB1DC5E7F);
        assert_eq!(decoded.magic_header, 0x4153);
        assert_eq!(decoded.version, 0x01);
        assert_eq!(decoded.flags, 0x01);
    }

    #[test]
    fn test_golden_vector_is_exactly_64_bytes() {
        let hex_vector = concat!(
            "6500000000000000",
            "15cd853dfe9c9717",
            "efcdab1032547698",
            "cdcccc3dcdcc4cbe",
            "9a99993ecdccccbe",
            "0000003f9a9919bf",
            "0000603fd4c3b2a1",
            "7f5edcb1",
            "53410101",
        );

        let bytes = hex::decode(hex_vector).expect("golden vector must be valid hexadecimal");
        assert_eq!(bytes.len(), 64);

        assert_eq!(&bytes[56..60], &[0x7f, 0x5e, 0xdc, 0xb1]);
        assert_eq!(&bytes[60..62], &[0x53, 0x41]);
        assert_eq!(bytes[62], 0x01);
        assert_eq!(bytes[63], 0x01);
    }

    #[test]
    fn test_crc32c_matches_wire_checksum() {
        let hex_vector = concat!(
            "6500000000000000",
            "15cd853dfe9c9717",
            "efcdab1032547698",
            "cdcccc3dcdcc4cbe",
            "9a99993ecdccccbe",
            "0000003f9a9919bf",
            "0000603fd4c3b2a1",
            "7f5edcb1",
            "53410101",
        );

        let bytes = hex::decode(hex_vector).expect("valid golden vector");
        let computed_crc = crc32c::crc32c(&bytes[0..56]);
        assert_eq!(computed_crc, 0xB1DC5E7F);

        let wire_crc = u32::from_le_bytes(bytes[56..60].try_into().unwrap());
        assert_eq!(wire_crc, computed_crc);
    }
}
