"""Nominal rate table shared with firmware; no hardware capability inference."""
from pathlib import Path
import re
SOURCE=Path(__file__).resolve().parents[2]/'firmware/sdr_receiver/sample_rate.h'

def nominal_rate(index):
    match=re.search(r'rates\[\]\s*=\s*\{([^}]+)\}',SOURCE.read_text(encoding='utf8'))
    if not match:raise ValueError('unrecognized nominal rate table')
    rates=[int(v.strip().removesuffix('u')) for v in match[1].split(',')]
    if type(index) is not int or not 0<=index<len(rates):raise ValueError('invalid bandwidth index')
    return rates[index]
