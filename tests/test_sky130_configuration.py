"""Reject damaged or wrong-target configuration streams before any loader use."""
import unittest
from compiler.sky130_user_design import validate_configuration


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.bit=bytes.fromhex('00AAFF01000000010000000000000000FAB0FAB1')
        for column in range(21):
            for frame in range(20):
                self.bit+=((column<<27)|(1<<frame)).to_bytes(4,'big')+bytes(80)
        self.bit+=bytes.fromhex('00100000')

    def test_complete_stream_and_hex_agree(self):
        self.assertEqual(validate_configuration(self.bit,self.bit.hex())['bytes'],35304)

    def test_truncated_stream_rejected(self):
        with self.assertRaisesRegex(ValueError,'length'):
            validate_configuration(self.bit[:-4],self.bit[:-4].hex())

    def test_wrong_frame_order_rejected(self):
        damaged=self.bit[:20]+bytes.fromhex('00000002')+self.bit[24:]
        with self.assertRaisesRegex(ValueError,'frame header'):
            validate_configuration(damaged,damaged.hex())

    def test_wrong_hex_rejected(self):
        with self.assertRaisesRegex(ValueError,'Hex export'):
            validate_configuration(self.bit,'00')

    def test_wrong_target_rejected(self):
        with self.assertRaisesRegex(ValueError,'length'):
            validate_configuration(bytes(16384),bytes(16384).hex())

    def test_missing_desync_rejected(self):
        damaged=self.bit[:-4]+bytes(4)
        with self.assertRaisesRegex(ValueError,'desynchronization'):
            validate_configuration(damaged,damaged.hex())
