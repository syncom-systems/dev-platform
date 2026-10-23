//! A small library with a unit test and a doctest.

/// Adds two numbers.
///
/// ```
/// assert_eq!(demo::add(1, 2), 3);
/// ```
pub fn add(a: i32, b: i32) -> i32 {
    a + b
}

#[cfg(test)]
mod tests {
    #[test]
    fn adds() {
        assert_eq!(super::add(2, 3), 5);
    }
}
