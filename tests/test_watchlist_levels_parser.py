import unittest

from ripster_scanner.watchlist_levels import parse_levels


class LevelParserTests(unittest.TestCase):
    def test_literal_direction_and_operator_variants(self):
        for note in ('LONG > $250', 'long above 250', 'Long over 250'):
            self.assertEqual([(x.direction, float(x.price)) for x in parse_levels(note)], [('LONG', 250)])
        for note in ('SHORT < 184', 'short below $184', 'Short under 184'):
            self.assertEqual([(x.direction, float(x.price)) for x in parse_levels(note)], [('SHORT', 184)])

    def test_actual_fixture_explicit_conditions_and_distinct_levels(self):
        text = '200 Psych Setup breakout, Bullish bias to long over 200, Short under 198'
        self.assertEqual([(x.direction, float(x.price)) for x in parse_levels(text)], [('LONG', 200), ('SHORT', 198)])
        self.assertEqual(len(parse_levels('LONG > 250; LONG > 260; LONG > 250.00')), 2)
        self.assertEqual(len(parse_levels('Long over 72, No go under 71.50, MTF target above, Bullish Bias')), 1)

    def test_no_invented_or_ambiguous_numeric_triggers(self):
        for note in ('No go', 'No go under 224/225', 'Support 250 Resistance 260',
                     'Long over PMH', 'Short the POPs vs 42', 'Long if 1h MTF holds',
                     'LONG > 250-260', 'LONG > 250/260', 'LONG > 1,000',
                     'LONG > 10%', 'LONG above 10 percent',
                     'SHORT >= 184', 'LONG below 250', 'not long above 250',
                     'LONG > 0', 'LONG > 1.123456789'):
            with self.subTest(note=note):
                self.assertEqual(parse_levels(note), ())
