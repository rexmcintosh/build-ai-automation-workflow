"""Throwaway file to exercise the Venice review Action end-to-end."""


def divide(a, b):
    # intentionally no zero-division guard, to give the panel something real
    return a / b


def read_config(path):
    # intentionally unclosed file handle + no error handling
    return eval(open(path).read())  # noqa — deliberately risky for the review
