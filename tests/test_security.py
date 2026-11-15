import unittest

from security import constant_time_equal, hash_password, verify_password


class PasswordHashTests(unittest.TestCase):
    def test_hash_does_not_contain_plaintext_and_verifies_password(self):
        password = "correct horse battery staple"
        encoded = hash_password(password)
        self.assertNotIn(password, encoded)
        self.assertTrue(verify_password(password, encoded))

    def test_hashes_use_independent_random_salts(self):
        first = hash_password("same password")
        second = hash_password("same password")
        self.assertNotEqual(first, second)
        self.assertTrue(verify_password("same password", first))
        self.assertTrue(verify_password("same password", second))

    def test_wrong_password_is_rejected(self):
        encoded = hash_password("correct password")
        self.assertFalse(verify_password("wrong password", encoded))

    def test_malformed_or_unsupported_hash_is_rejected(self):
        for encoded in ("", "plain-text-password", "scrypt$999999999$8$1$YQ==$YQ=="):
            with self.subTest(encoded=encoded):
                self.assertFalse(verify_password("anything", encoded))

    def test_constant_time_comparison_handles_missing_values(self):
        self.assertTrue(constant_time_equal("token", "token"))
        self.assertFalse(constant_time_equal("token", "wrong"))
        self.assertFalse(constant_time_equal("token", None))


if __name__ == "__main__":
    unittest.main()
