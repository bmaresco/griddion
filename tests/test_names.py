from football_trivia.names import norm_name


def test_initials_collapse():
    assert norm_name("Y. A. Tittle") == norm_name("Y.A. Tittle") == "ya tittle"
    assert norm_name("J. J. Jones") == norm_name("J.J. Jones")


def test_suffix_accents_hyphen():
    assert norm_name("Odell Beckham Jr.") == "odell beckham"
    assert norm_name("Amon-Ra St. Brown") == "amon ra st brown"
    assert norm_name("Hélder Sánchez") == "helder sanchez"
