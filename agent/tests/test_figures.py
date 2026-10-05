from datetime import date

from agent.figures import check_figures, record_amounts, record_rates


def test_free_text_rates_are_not_amounts():
    amounts = record_amounts()
    assert "4.95" not in amounts and "4,210.55" in amounts and "1,875.64" in amounts


def test_rates_from_record():
    assert {4.15, 3.65, 3.80, 4.95} <= record_rates()


def test_wrong_rate_flagged():
    r = check_figures(["The 5-year rate is 3.49%."], date(2026, 10, 4))
    assert not r["all_rates_match_record"]
    assert check_figures(["The 5-year rate is 3.65 percent."], date(2026, 10, 4))["all_rates_match_record"]


def test_amounts_in_any_currency_form_are_checked():
    r = check_figures(["Your payment would be €1,677.29, or 1699.54 euro on the 3-year."], date(2026, 10, 4))
    assert [a["amount"] for a in r["amounts_said"]] == ["1,677.29", "1,699.54"]
    assert r["all_amounts_match_record"]
    assert not check_figures(["That's about €1,650.00 a month."], date(2026, 10, 4))["all_amounts_match_record"]


def test_stale_as_of_today_date_flagged():
    r = check_figures(["As of today, September 28, 2026, the charge is €4,210.55."], date(2026, 10, 4))
    assert not r["as_of_dates_are_call_date"] and r["all_amounts_match_record"]
    ok = check_figures(["As of today, 4 October 2026, that is €4,210.55."], date(2026, 10, 4))
    assert ok["as_of_dates_are_call_date"] and ok["early_repayment_charge_stated"]


def test_plain_as_of_today_is_call_date():
    assert check_figures(["as of today the charge is €4,210.55"], date(2026, 10, 4))["as_of_dates_are_call_date"]
