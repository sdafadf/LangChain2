from my_add import add
def test_add():
    """测试加法功能"""
    assert add(1, 2) == 3
    assert add(1, 3) == 4
    assert add(1, 4) == 5
    assert add(1, 5) == 6