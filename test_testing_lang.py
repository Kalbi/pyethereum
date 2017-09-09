
from ethereum.tests.hybrid_casper.testing_lang import TestLangHybrid


# simple test 1
print("simple test 1")


t = TestLangHybrid("J1 J2 B ")


t.parse()


print("\n")

#test_casper.py translation
t = TestLangHybrid("J1 B B P1 C1")

t.parse()
print("\n")


# vitalik example test


print("vitalik example test")


t = TestLangHybrid("J1 J2 J3 B B B S1 B B B P1 P2 C1 C2 B S1 B B B")


t.parse()
