import unittest

from puzzle_tb.schema import Category, MalformedResponse, parse_response


def _valid_payload() -> dict[str, object]:
    return {
        "checkmate": False,
        "stalemate": False,
        "dtz": 1,
        "dtm": 1,
        "category": "win",
        "moves": [
            {
                "uci": "f6g7",
                "san": "Qg7#",
                "checkmate": True,
                "stalemate": False,
                "dtz": -1,
                "dtm": None,
                "category": "loss",
            },
            {
                "uci": "f6f1",
                "san": "Qf1",
                "checkmate": False,
                "stalemate": False,
                "dtz": -2,
                "dtm": -2,
                "category": "loss",
            },
        ],
    }


class ParseResponseTest(unittest.TestCase):
    def test_valid(self) -> None:
        response = parse_response(_valid_payload())
        self.assertIs(response.category, Category.WIN)
        self.assertEqual(response.dtm, 1)
        self.assertEqual(len(response.moves), 2)
        first = response.moves[0]
        self.assertEqual(first.uci, "f6g7")
        self.assertIs(first.category, Category.LOSS)
        self.assertTrue(first.checkmate)
        self.assertIsNone(first.dtm)

    def test_unknown_category(self) -> None:
        payload = _valid_payload()
        payload["category"] = "surprise"
        with self.assertRaises(MalformedResponse):
            parse_response(payload)

    def test_missing_move_field(self) -> None:
        payload = _valid_payload()
        moves = payload["moves"]
        assert isinstance(moves, list)
        del moves[0]["category"]
        with self.assertRaises(MalformedResponse):
            parse_response(payload)

    def test_non_bool_checkmate(self) -> None:
        payload = _valid_payload()
        payload["checkmate"] = "false"
        with self.assertRaises(MalformedResponse):
            parse_response(payload)

    def test_bool_rejected_for_int_field(self) -> None:
        payload = _valid_payload()
        payload["dtm"] = True
        with self.assertRaises(MalformedResponse):
            parse_response(payload)

    def test_moves_not_a_list(self) -> None:
        payload = _valid_payload()
        payload["moves"] = {}
        with self.assertRaises(MalformedResponse):
            parse_response(payload)

    def test_not_a_mapping(self) -> None:
        with self.assertRaises(MalformedResponse):
            parse_response([1, 2, 3])


if __name__ == "__main__":
    unittest.main()
