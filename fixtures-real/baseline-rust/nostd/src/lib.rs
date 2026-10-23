//! Minimal `no_std` core of a bare-metal AArch64 kernel.
#![no_std]

/// Adds two page counts, wrapping like a hardware counter.
pub const fn add_pages(a: usize, b: usize) -> usize {
    a.wrapping_add(b)
}

/// Parks the core until an event arrives; only exists where the instruction does.
#[cfg(target_arch = "aarch64")]
pub fn halt() -> ! {
    loop {
        // SAFETY: `wfe` only waits for an event and has no memory or register effects.
        unsafe { core::arch::asm!("wfe", options(nomem, nostack)) }
    }
}
