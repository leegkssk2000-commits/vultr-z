import math, random
from collections import defaultdict

class Thompson:
    def __init__(self): self.ab = defaultdict(lambda:[1.0,1.0]) # Beta(a,b)
    def sample(self, name): 
        a,b = self.ab[name]; 
        return random.betavariate(a,b)
    def update(self, name, reward): # reward∈[0,1]
        a,b = self.ab[name]
        if reward>=0.5: a+=1
        else: b+=1
        self.ab[name]=[a,b]
    def pick(self, names, k=3):
        return [n for n,_ in sorted([(n,self.sample(n)) for n in names], key=lambda x:x[1], reverse=True)[:k]]