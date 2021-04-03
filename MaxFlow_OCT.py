import numpy as np
import gurobipy as gp
from dataset import dataloader



class MaxFlow_OCT():

    def __init__(self, args):
        '''
        Intiialize the class
        :param args: the dict of arguments, must include
        '''

        self.max_depth = args['max_depth']
        self.lambda_ = args['lambda']

        # intialize the tree
        self.B = list(range(2 ** self.max_depth - 1))
        self.T = list(range(2 ** self.max_depth - 1, 2 ** (self.max_depth + 1) - 1))
        self.A = [self.tree_ancestor(n) for n in self.B + self.T]

    def tree_children(self, node):
        '''
        given a node, return its left and right children in the tree
        :param node:
        :return:
        '''

        return 2 * node + 1, 2 * node + 2

    def tree_parent(self, node):

        if node == 0:
            return None
        elif node % 2 == 1:
            return int(node // 2)
        else:
            return int(node // 2) - 1

    def tree_ancestor(self, node):
        '''
        find the acesestor of the given node in the tree
        :param node:
        :return:
        '''

        ancestor = []
        parent = self.tree_parent(node)

        while parent is not None:
            ancestor.append(parent)
            parent = self.tree_parent(parent)

        return ancestor

    def tree_construction(self):

        b_val = self.master.getAttr('x', self.b)
        w_val = self.master.getAttr('x', self.w)

        self.branches = {n: f for n in self.B for f in self.F if b_val[n,f] >= 0.999}
        self.labels = {n: k for n in self.B + self.T for k in self.K if w_val[n, k] >= 0.999}

    @staticmethod
    def min_cut(model, where):
        if where == gp.GRB.Callback.MIPSOL:
            b_val = model.cbGetSolution(model._b)
            w_val = model.cbGetSolution(model._w)
            p_val = model.cbGetSolution(model._p)
            g_val = model.cbGetSolution(model._g)

            for i in model._I:
                S, dir = [], []
                n = 0

                while (n in model._B) and (p_val[n] == 0):
                    S.append(n)
                    if np.sum([b_val[n, f] for f in model._F if model._X[i, f] <= 1e-5]) >= 0.999:
                        n = 2 * n + 1
                        dir.append(0)
                    elif np.sum([b_val[n, f] for f in model._F if model._X[i, f] >= 0.999]) >= 0.999:
                        n = 2 * n + 2
                        dir.append(1)


                S.append(n)
                if g_val[i] > np.sum([w_val[n, k] for k in model._K if model._Y[i] == k]):
                    model.cbLazy(model._g[i] <=
                                 gp.quicksum(model._b[val, f]
                                             for idx, val in enumerate(S[:-1])
                                             for f in model._F
                                             if model._X[i,f] == 1 - dir[idx]) +
                                 gp.quicksum(model._w[j, k]
                                             for j in S for k in model._K
                                             if model._Y[i] == k)
                                 )

    def fit(self, x, y):
        '''
        Fit the classification tree
        :param x: the array of features, the faetures are assumed to be binary, i.e. 0/1
        :param y: the array of labels, the labels are assumed to be ordered integers starting from 0, i.e. 0, 1, 2, ...
        :return:
        '''

        self.x = x
        self.y = y
        self.n, self.m = self.x.shape

        # the number of distinct labels
        self.K = list(range(np.max(self.y)+1))
        # the set of training data
        self.I = list(range(self.n))
        # the set of features
        self.F = list(range(self.m))

        # intialize the master problem
        self.master = gp.Model('master')
        self.master.Params.outputFlag = 0

        # add decision variables
        b_idx = [(n, f) for n in self.B for f in self.F]
        self.b = self.master.addVars(b_idx, name = 'b', vtype=gp.GRB.BINARY)
        w_idx = [(n, k) for n in self.B + self.T for k in self.K]
        self.w = self.master.addVars(w_idx, name = 'w', vtype=gp.GRB.BINARY)
        g_idx = [i for i in self.I]
        self.g = self.master.addVars(g_idx, name = 'g', lb = 0, ub = 1, vtype=gp.GRB.CONTINUOUS)
        p_idx = [n for n in self.B + self.T]
        self.p = self.master.addVars(p_idx, name = 'P', vtype=gp.GRB.BINARY)

        # add constraints
        self.master.addConstrs((gp.quicksum(self.b[n, f] for f in self.F)
                                + self.p[n]
                                + gp.quicksum(self.p[m] for m in self.A[n])
                                == 1
                                for n in self.B),
                               name = 'branching_nodes')

        self.master.addConstrs((self.p[n]
                                + gp.quicksum(self.p[m] for m in self.A[n])
                                == 1
                                for n in self.T),
                               name='terminal_nodes')

        self.master.addConstrs((gp.quicksum(self.w[n, k] for k in self.K) == self.p[n]
                                for n in self.B + self.T)
                               ,name = 'label_assignment')

        # set objective function
        obj = (1 - self.lambda_) * gp.quicksum(self.g[i] for i in self.I) - \
               self.lambda_ * gp.quicksum(self.b[n,f] for (n,f) in b_idx)
        self.master.setObjective(obj, gp.GRB.MAXIMIZE)

        # enable lazy cuts
        self.master.Params.lazyConstraints = 1
        self.master._I = self.I
        self.master._B = self.B
        self.master._T = self.T
        self.master._F = self.F
        self.master._X = self.x
        self.master._Y = self.y
        self.master._K = self.K

        self.master._b = self.b
        self.master._w = self.w
        self.master._p = self.p
        self.master._g = self.g
        self.master.optimize(self.min_cut)

        # self.master.display()
        # print(self.master.printAttr('X'))
        self.tree_construction()

    def predict(self, x):

        pred = []
        for val in x:
            n = 0
            while n not in self.labels:
                f = self.branches[n]
                if val[f] == 0:
                    n = n * 2 + 1
                else:
                    n = n * 2 + 2
            pred.append(self.labels[n])
        return pred

    def eval(self, x, y, metric = 'accuracy'):

        y_pred = self.predict(x)
        if metric == 'accuracy':
            n_corr = (y_pred == y).sum()
            return n_corr / len(y)

        return None

if __name__ == '__main__':

    args = {'max_depth': 2, 'lambda': 0}
    # x = np.array([[1,0,0], [1,0,0], [0,1,0], [1,1,1], [1,0,1]])
    # y = np.array([0,0,1,0,0])
    # x_test = np.array([[0,0,0], [1,1,0]])

    x_train, x_test, y_train, y_test = dataloader('monk1')

    model = MaxFlow_OCT(args)
    model.fit(x_train, y_train)
    # print(model.predict(x_train))
    # print(y_train)
    print(model.branches)
    print(model.labels)
    print('train: ', model.eval(x_train, y_train))
    print('test: ', model.eval(x_test, y_test))