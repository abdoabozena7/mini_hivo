import argparse
import json
p=argparse.ArgumentParser()
p.add_argument("a",type=int); p.add_argument("b",type=int)
a=p.parse_args()
print(json.dumps({"sum":a.a+a.b}))
