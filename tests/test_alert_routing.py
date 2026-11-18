"""Routing regressions using only synthetic employee records."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import alert_contacts as routing


def person(n, group='employee', dept='تولید روغن', line='خط ۲', **extra):
    return dict(mac=f'aa:bb:cc:dd:ee:{n:02x}', name=f'Person {n}', staff_group=group,
                company='Factory', dept=dept, line=line, registered=True,
                present=True, scan_allowed=True, **extra)


class RoutingTests(unittest.TestCase):
    def test_worker_targets_all_hse_and_local_leader_only(self):
        source = person(1)
        rows = [source, person(2, 'hse'), person(3, 'hse', dept='انبار'),
                person(4, 'shift_leader'), person(5, 'supervisor'),
                person(6, 'shift_leader', dept='تولید پلاستیک')]
        self.assertEqual({p['mac'] for p in routing.alert_recipients(source, rows)},
                         {rows[i]['mac'] for i in (1, 2, 3)})

    def test_alert_on_supervisor_or_shift_leader_goes_to_all_hse(self):
        for group in ('supervisor', 'shift_leader'):
            source = person(1, group)
            rows = [source, person(2, 'hse'), person(3, 'hse', dept='انبار'),
                    person(4, 'shift_leader')]
            self.assertEqual({p['mac'] for p in routing.alert_recipients(source, rows)},
                             {rows[1]['mac'], rows[2]['mac']})

    def test_common_words_do_not_match_another_unit_or_line(self):
        source = person(1)
        for candidate in (person(2, 'shift_leader', dept='تولید پلاستیک'),
                          person(3, 'shift_leader', line='خط ۱')):
            self.assertIsNone(routing.resolve_alert_contact(source, [candidate]))

    def test_missing_presence_registration_and_invalid_mac_are_rejected(self):
        source = person(1)
        for field, value in (('present', False), ('registered', False), ('mac', 'bad')):
            candidate = person(2, 'shift_leader'); candidate[field] = value
            self.assertIsNone(routing.resolve_alert_contact(source, [candidate]))


if __name__ == '__main__': unittest.main()
