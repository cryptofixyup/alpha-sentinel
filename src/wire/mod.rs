pub mod wire {
    #[repr(C)]
    #[derive(Debug, Clone, Copy, PartialEq)]
    pub struct VersionedTelemetryFrame {
        pub sequence_id: u64,
        pub timestamp_ns: u64,
        pub device_id_hash: u64,
        pub signal_metrics: [f32; 6],
        pub anomaly_score: f32,
        pub nonce: u32,
        pub checksum: u32,
        pub magic_header: u16,
        pub version: u8,
        pub flags: u8,
    }

    pub const FRAME_SIZE: usize = 64;
    pub const HEADER_SIZE: usize = 56;

    pub const MAGIC: u16 = 0x4153;
    pub const VERSION: u8 = 0x01;

    const _: () = assert!(
        core::mem::size_of::<VersionedTelemetryFrame>() == FRAME_SIZE
    );

    const _: () = assert!(
        core::mem::align_of::<VersionedTelemetryFrame>() == 8
    );

    impl VersionedTelemetryFrame {
        #[inline]
        pub fn decode_from_wire(
            bytes: &[u8],
        ) -> Result<Self, &'static str> {
            if bytes.len() != FRAME_SIZE {
                return Err("INVALID_FRAME_LENGTH");
            }

            let magic = u16::from_le_bytes([bytes[60], bytes[61]]);
            if magic != MAGIC {
                return Err("INVALID_MAGIC_HEADER");
            }

            if bytes[62] != VERSION {
                return Err("UNSUPPORTED_PROTOCOL_VERSION");
            }

            let checksum =
                u32::from_le_bytes([bytes[56], bytes[57], bytes[58], bytes[59]]);

            let computed = crc32c::crc32c(&bytes[..HEADER_SIZE]);
            if computed != checksum {
                return Err("CHECKSUM_MISMATCH");
            }

            let sequence_id =
                u64::from_le_bytes(bytes[0..8].try_into().unwrap());
            let timestamp_ns =
                u64::from_le_bytes(bytes[8..16].try_into().unwrap());
            let device_id_hash =
                u64::from_le_bytes(bytes[16..24].try_into().unwrap());

            let mut signal_metrics = [0.0_f32; 6];
            let mut i = 0;
            while i < 6 {
                let offset = 24 + i * 4;
                let bits = u32::from_le_bytes(
                    bytes[offset..offset + 4].try_into().unwrap()
                );
                let value = f32::from_bits(bits);
                if !value.is_finite() {
                    return Err("INVALID_METRIC_VALUE");
                }
                signal_metrics[i] = value;
                i += 1;
            }

            let anomaly_score = f32::from_bits(
                u32::from_le_bytes(bytes[48..52].try_into().unwrap())
            );
            if !anomaly_score.is_finite() || !(0.0..=1.0).contains(&anomaly_score) {
                return Err("INVALID_ANOMALY_SCORE");
            }

            let nonce =
                u32::from_le_bytes(bytes[52..56].try_into().unwrap());

            Ok(Self {
                sequence_id,
                timestamp_ns,
                device_id_hash,
                signal_metrics,
                anomaly_score,
                nonce,
                checksum,
                magic_header: magic,
                version: bytes[62],
                flags: bytes[63],
            })
        }
    }
}

include!("tests.rs");
