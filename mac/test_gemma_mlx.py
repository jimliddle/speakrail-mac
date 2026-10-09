import unittest

import mlx.core as mx
import numpy as np

from gemma_mlx import convert_weights


class WeightConversionTests(unittest.TestCase):
    def test_all_int4_values_and_scales(self):
        signed = np.tile(np.arange(-8, 8, dtype=np.int32), (5, 4))
        unsigned = (signed + 8).astype(np.uint32).reshape(5, 8, 8)
        packed = np.bitwise_or.reduce(unsigned << (4 * np.arange(8, dtype=np.uint32)), axis=-1)
        scales = np.array([[0.125, 0.25]] * 5, dtype=np.float32)
        source = "model.language_model.layers.0.mlp.gate_proj"
        raw = {source + ".weight_packed": mx.array(packed.view(np.int32)),
               source + ".weight_shape": mx.array([5, 64]),
               source + ".weight_scale": mx.array(scales)}
        weights, paths = convert_weights(raw)
        stem = paths[0]
        decoded = mx.dequantize(weights[stem + ".weight"], weights[stem + ".scales"],
                                weights[stem + ".biases"], group_size=32, bits=4)
        expected = signed * np.repeat(scales, 32, axis=1)
        np.testing.assert_array_equal(np.array(decoded), expected)

    def test_reject_wrong_shape(self):
        source = "model.language_model.layers.0.mlp.gate_proj"
        raw = {source + ".weight_packed": mx.zeros((5, 9), dtype=mx.int32),
               source + ".weight_shape": mx.array([5, 64]),
               source + ".weight_scale": mx.ones((5, 2))}
        with self.assertRaises(ValueError):
            convert_weights(raw)

    def test_reject_empty_checkpoint(self):
        with self.assertRaises(ValueError):
            convert_weights({})


if __name__ == "__main__":
    unittest.main()
