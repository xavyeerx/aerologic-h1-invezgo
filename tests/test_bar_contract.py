import unittest

import pandas as pd
import pytz
from datetime import datetime

from core.bar_contract import (
    INVEZGO_H1_CONTRACT,
    attach_bar_contract,
    read_bar_contract,
    require_price_signal_eligible,
)
from core.data_provider import _rows_to_h1_ohlc_df


class BarContractTests(unittest.TestCase):
    def test_closed_h1_provider_bars_are_signal_eligible(self):
        frame = _rows_to_h1_ohlc_df(
            [{"date": "2026-07-17T09:00:00Z", "open": 10, "high": 12,
              "low": 9, "close": 11, "volume": 100}],
            now=pytz.timezone("Asia/Jakarta").localize(datetime(2026, 7, 17, 10, 1)),
        )
        contract = require_price_signal_eligible(frame)
        self.assertEqual(contract, INVEZGO_H1_CONTRACT)
        self.assertEqual(frame.index[0].hour, 9)


    def test_missing_provenance_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "no bar_contract"):
            require_price_signal_eligible(pd.DataFrame({"close": [1]}))

    def test_attach_preserves_rows_and_records_contract(self):
        frame = pd.DataFrame({"close": [1, 2]})
        returned = attach_bar_contract(frame, INVEZGO_H1_CONTRACT)
        self.assertIs(returned, frame)
        self.assertEqual(len(returned), 2)
        self.assertEqual(read_bar_contract(returned).scheme, "invezgo_h1_live_v1")


if __name__ == "__main__":
    unittest.main()
