import sys, json, pandas as pd
r = json.load(open(sys.argv[1]))
cols = sys.argv[2].split(",")
for ind, d in r.items():
    df = pd.DataFrame(d).T[cols]
    print("==", ind); print(df.to_string(float_format=lambda v: f"{v:.3f}"))
