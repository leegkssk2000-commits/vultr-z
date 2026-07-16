R4.1 marker matching rule:

1. Find each marker occurrence.
2. If the marker starts with an identifier character, the preceding character must not be an identifier character.
3. If the marker ends with an identifier character, the following character must not be an identifier character.
4. Therefore `partial_fill` does not match `partial_fill_match`.
