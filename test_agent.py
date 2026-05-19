import unittest
from agent import AgenticLoop

class TestAgenticLoop(unittest.TestCase):
    def test_initialization(self):
        loop = AgenticLoop()
        self.assertEqual(loop.status, "active")
    
    def test_error_handling(self):
        loop = AgenticLoop()
        loop.status = None
        with self.assertRaises(RuntimeError):
            loop.start()

if __name__ == "__main__":
    unittest.main()