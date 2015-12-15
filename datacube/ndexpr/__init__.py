# ------------------------------------------------------------------------------
# Name:       ndexpr.py
# Purpose:    ndarray Math Expression evaluator
#
# Author:     Peter Wang
#
# Created:    7 October 2015
# Copyright:  2015 Commonwealth Scientific and Industrial Research Organisation
#             (CSIRO)
#             Code based on PyParsing fourFn example by Paul McGuire
#             Used with his with permission
#             (http://pyparsing.wikispaces.com/file/view/fourFn.py)
#             Adapted get_pqa_mask function from stacker.py by Josh Sixsmith &
#             Alex IP of Geoscience Australia
#             https://github.com/GeoscienceAustralia/agdc/blob/master/src/stacker.py
# License:    This software is open source under the Apache v2.0 License
#             as provided in the accompanying LICENSE file or available from
#             https://github.com/data-cube/agdc-v2/blob/master/LICENSE
#             By continuing, you acknowledge that you have read and you accept
#             and will abide by the terms of the License.
#
# Updates:
# 7/10/2015:  Initial Version.
#
# ------------------------------------------------------------------------------

from __future__ import absolute_import
from __future__ import print_function
import math
import operator
import inspect
import sys
import ctypes
import numpy as np
import xray
from xray import ufuncs
from scipy import ndimage
from pprint import pprint
import matplotlib.pyplot as plt

from pyparsing import Literal, CaselessLiteral, Word, Combine, Group,\
    Optional, ZeroOrMore, Forward, nums, alphas, delimitedList,\
    ParserElement, FollowedBy

ParserElement.enablePackrat()


class NDexpr(object):

    def __init__(self):

        self.ae = False

        self.exprStack = []
        self.topStack = []
        self.texprStack = []

        # Define constants
        self.constants = {}

        # Define Operators
        self.opn = {"+": operator.add,
                    "-": operator.sub,
                    "*": operator.mul,
                    "/": operator.truediv,
                    ">": operator.gt,
                    ">=": operator.ge,
                    "<": operator.lt,
                    "<=": operator.le,
                    "==": operator.eq,
                    "!=": operator.ne,
                    "|": operator.or_,
                    "&": operator.and_,
                    "!": operator.inv}

        # Define Xray DataArray operators with 1 input parameter
        self.xfn1 = {"angle": xray.ufuncs.angle,
                     "arccos": xray.ufuncs.arccos,
                     "arccosh": xray.ufuncs.arccosh,
                     "arcsin": xray.ufuncs.arcsin,
                     "arcsinh": xray.ufuncs.arcsinh,
                     "arctan": xray.ufuncs.arctan,
                     "arctanh": xray.ufuncs.arctanh,
                     "ceil": xray.ufuncs.ceil,
                     "conj": xray.ufuncs.conj,
                     "cos": xray.ufuncs.cos,
                     "cosh": xray.ufuncs.cosh,
                     "deg2rad": xray.ufuncs.deg2rad,
                     "degrees": xray.ufuncs.degrees,
                     "exp": xray.ufuncs.exp,
                     "expm1": xray.ufuncs.expm1,
                     "fabs": xray.ufuncs.fabs,
                     "fix": xray.ufuncs.fix,
                     "floor": xray.ufuncs.floor,
                     "frexp": xray.ufuncs.frexp,
                     "imag": xray.ufuncs.imag,
                     "iscomplex": xray.ufuncs.iscomplex,
                     "isfinite": xray.ufuncs.isfinite,
                     "isinf": xray.ufuncs.isinf,
                     "isnan": xray.ufuncs.isnan,
                     "isreal": xray.ufuncs.isreal,
                     "log": xray.ufuncs.log,
                     "log10": xray.ufuncs.log10,
                     "log1p": xray.ufuncs.log1p,
                     "log2": xray.ufuncs.log2,
                     "rad2deg": xray.ufuncs.rad2deg,
                     "radians": xray.ufuncs.radians,
                     "real": xray.ufuncs.real,
                     "rint": xray.ufuncs.rint,
                     "sign": xray.ufuncs.sign,
                     "signbit": xray.ufuncs.signbit,
                     "sin": xray.ufuncs.sin,
                     "sinh": xray.ufuncs.sinh,
                     "sqrt": xray.ufuncs.sqrt,
                     "square": xray.ufuncs.square,
                     "tan": xray.ufuncs.tan,
                     "tanh": xray.ufuncs.tanh,
                     "trunc": xray.ufuncs.trunc}

        # Define Xray DataArray operators with 2 input parameter
        self.xfn2 = {"arctan2": xray.ufuncs.arctan2,
                     "copysign": xray.ufuncs.copysign,
                     "fmax": xray.ufuncs.fmax,
                     "fmin": xray.ufuncs.fmin,
                     "fmod": xray.ufuncs.fmod,
                     "hypot": xray.ufuncs.hypot,
                     "ldexp": xray.ufuncs.ldexp,
                     "logaddexp": xray.ufuncs.logaddexp,
                     "logaddexp2": xray.ufuncs.logaddexp2,
                     "logicaland": xray.ufuncs.logical_and,
                     "logicalnot": xray.ufuncs.logical_not,
                     "logicalor": xray.ufuncs.logical_or,
                     "logicalxor": xray.ufuncs.logical_xor,
                     "maximum": xray.ufuncs.maximum,
                     "minimum": xray.ufuncs.minimum,
                     "nextafter": xray.ufuncs.nextafter}

        # Define non-Xray DataArray operators with 2 input parameter
        self.fn2 = {"percentile": np.percentile}

        # Define Xray DataArray reduction operators
        self.xrfn = {"all": xray.DataArray.all,
                     "any": xray.DataArray.any,
                     "argmax": xray.DataArray.argmax,
                     "argmin": xray.DataArray.argmin,
                     "max": xray.DataArray.max,
                     "mean": xray.DataArray.mean,
                     "median": xray.DataArray.median,
                     "min": xray.DataArray.min,
                     "prod": xray.DataArray.prod,
                     "sum": xray.DataArray.sum,
                     "std": xray.DataArray.std,
                     "var": xray.DataArray.var}

        # Define non-Xray DataArray operators with 2 input parameter
        self.xcond = {"<": np.percentile}

        # Define Grammar
        point = Literal(".")
        e = CaselessLiteral("E")
        fnumber = Combine(Word("+-"+nums, nums) +
                          Optional(point + Optional(Word(nums))) +
                          Optional(e + Word("+-"+nums, nums)))
        variable = Word(alphas, alphas+nums+"_$")

        seq = Literal("=")
        b_not = Literal("~")
        plus = Literal("+")
        minus = Literal("-")
        mult = Literal("*")
        div = Literal("/")
        gt = Literal(">")
        gte = Literal(">=")
        lt = Literal("<")
        lte = Literal("<=")
        eq = Literal("==")
        neq = Literal("!=")
        b_or = Literal("|")
        b_and = Literal("&")
        l_not = Literal("!")
        lpar = Literal("(").suppress()
        rpar = Literal(")").suppress()
        comma = Literal(",")
        colon = Literal(":")
        lbrac = Literal("[")
        rbrac = Literal("]")
        lcurl = Literal("{")
        rcurl = Literal("}")
        qmark = Literal("?")
        scolon = Literal(";")
        addop = plus | minus
        multop = mult | div
        sliceop = colon
        compop = gte | lte | gt | lt
        eqop = eq | neq
        bitcompop = b_or | b_and
        bitnotop = b_not
        logicalnotop = l_not
        assignop = seq
        expop = Literal("^")

        expr = Forward()
        indexexpr = Forward()

        atom = (Optional("-") +
                (variable + seq + expr).setParseAction(self.pushAssign) |
                indexexpr.setParseAction(self.pushIndex) |
                (lpar + expr + qmark.setParseAction(self.pushTernary1) + expr +
                 scolon.setParseAction(self.pushTernary2) + expr +
                 rpar).setParseAction(self.pushTernary) |
                (lpar + expr + qmark + expr + scolon + expr +
                 rpar).setParseAction(self.pushTernary) |
                (logicalnotop + expr).setParseAction(self.pushULNot) |
                (bitnotop + expr).setParseAction(self.pushUNot) |
                (variable + lcurl + expr +
                 rcurl).setParseAction(self.pushMask) |
                (variable + lpar + expr + (comma + expr)*3 +
                 rpar).setParseAction(self.pushExpr4) |
                (variable + lpar + expr + (comma + expr)*2 +
                 rpar).setParseAction(self.pushExpr3) |
                (variable + lpar + expr + comma + expr +
                 rpar).setParseAction(self.pushExpr2) |
                (variable + lpar + expr + rpar |
                 variable).setParseAction(self.pushExpr1) |
                fnumber.setParseAction(self.pushExpr) |
                (lpar + expr.suppress() +
                 rpar).setParseAction(self.pushUMinus)
                )

        # Define order of operations for operators

        factor = Forward()
        factor << atom + ZeroOrMore((expop + factor)
                                    .setParseAction(self.pushOp))
        term = factor + ZeroOrMore((multop + factor)
                                   .setParseAction(self.pushOp))
        term2 = term + ZeroOrMore((addop + term)
                                  .setParseAction(self.pushOp))
        term3 = term2 + ZeroOrMore((sliceop + term2)
                                   .setParseAction(self.pushOp))
        term4 = term3 + ZeroOrMore((compop + term3)
                                   .setParseAction(self.pushOp))
        term5 = term4 + ZeroOrMore((eqop + term4)
                                   .setParseAction(self.pushOp))
        term6 = term5 + ZeroOrMore((bitcompop + term5)
                                   .setParseAction(self.pushOp))
        expr << term6 + ZeroOrMore((assignop + term6)
                                   .setParseAction(self.pushOp))

        # Define index operators

        colon_expr = (colon + FollowedBy(comma) ^ colon +
                      FollowedBy(rbrac)).setParseAction(self.pushColon)
        range_expr = colon_expr | expr | colon
        indexexpr << (variable + lbrac + delimitedList(range_expr, delim=',') +
                      rbrac).setParseAction(self.pushExpr)

        self.parser = expr

    def setAE(self, flag):
        self.ae = flag

    def pushExpr(self, strg, loc, toks):
        self.exprStack.append(toks[0])

    def pushExpr1(self, strg, loc, toks):
        if toks[0] in self.xrfn:
            self.exprStack.append('1')
        self.exprStack.append(toks[0])

    def pushExpr2(self, strg, loc, toks):
        if toks[0] in self.xrfn:
            self.exprStack.append('2')
        self.exprStack.append(toks[0])

    def pushExpr3(self, strg, loc, toks):
        if toks[0] in self.xrfn:
            self.exprStack.append('3')
        self.exprStack.append(toks[0])

    def pushExpr4(self, strg, loc, toks):
        if toks[0] in self.xrfn:
            self.exprStack.append('4')
        self.exprStack.append(toks[0])

    def pushOp(self, strg, loc, toks):
        self.exprStack.append(toks[0])

    def pushUMinus(self, strg, loc, toks):
        if toks and toks[0] == '-':
            self.exprStack.append('unary -')

    def pushUNot(self, strg, loc, toks):
        if toks and toks[0] == '~':
            self.exprStack.append('unary ~')

    def pushULNot(self, strg, loc, toks):
        if toks and toks[0] == '!':
            self.exprStack.append('unary !')

    def pushIndex(self, strg, loc, toks):
        self.exprStack.append("[]")

    def pushColon(self, strg, loc, toks):
        self.exprStack.append("::")

    def pushMask(self, strg, loc, toks):
        self.exprStack.append(toks[0])
        self.exprStack.append("{}")

    def pushAssign(self, strg, loc, toks):
        self.exprStack.append(toks[0])
        self.exprStack.append("=")

    def pushTernary(self, strg, loc, toks):
        self.texprStack.append(self.exprStack)
        self.exprStack = []
        self.exprStack.append(self.texprStack[::-1])
        self.exprStack.append('?')
        self.exprStack = self.flatten_list(self.exprStack)
        self.texprStack = []

    def pushTernary1(self, strg, loc, toks):
        self.texprStack.append(self.exprStack)
        self.exprStack = []

    def pushTernary2(self, strg, loc, toks):
        self.texprStack.append(self.exprStack)
        self.exprStack = []

    def evaluateStack(self, s):
        op = s.pop()
        if op == 'unary -':
            return -self.evaluateStack(s)
        elif op == 'unary ~':
            return ~self.evaluateStack(s)
        elif op == 'unary !':
            return not self.evaluateStack(s)
        elif op == "=":
            op1 = s.pop()
            op2 = self.evaluateStack(s)
            self.f.f_globals[op1] = op2

            # code to write to locals, need to sort out when to write to locals/globals.
            # self.f.f_locals[op1] = op2
            # ctypes.pythonapi.PyFrame_LocalsToFast(ctypes.py_object(self.f), ctypes.c_int(1))
        elif op in self.opn.keys():
            op2 = self.evaluateStack(s)
            op1 = self.evaluateStack(s)
            if op == '+' and isinstance(op2, xray.DataArray) and \
               op2.dtype.type == np.bool_:
                return xray.DataArray.where(op1, op2)
            return self.opn[op](op1, op2)
        elif op == "::":
            return slice(None, None, None)
        elif op in self.xrfn:
            dim = int(self.evaluateStack(s))
            dims = ()
            for i in range(1, dim):
                dims += int(self.evaluateStack(s)),
            op1 = self.evaluateStack(s)

            args = {}
            if op == 'argmax' or op == 'argmin':
                if dim != 1:
                    args['axis'] = dims[0]
            elif dim != 1:
                args['axis'] = dims

            if 'skipna' in inspect.getargspec(self.xrfn[op])[0] and \
               op != 'prod':
                args['skipna'] = True

            val = self.xrfn[op](op1, **args)
            return val
        elif op in self.xfn1:
            val = self.xfn1[op](self.evaluateStack(s))

            if isinstance(val, tuple) or isinstance(val, np.ndarray):
                return xray.DataArray(val)
            return val
        elif op in self.xfn2:
            op2 = self.evaluateStack(s)
            op1 = self.evaluateStack(s)
            val = self.xfn2[op](op1, op2)

            if isinstance(val, tuple) or isinstance(val, np.ndarray):
                return xray.DataArray(val)
            return val
        elif op in self.fn2:
            op2 = self.evaluateStack(s)
            op1 = self.evaluateStack(s)
            val = self.fn2[op](op1, op2)

            if isinstance(val, tuple) or isinstance(val, np.ndarray):
                return xray.DataArray(val)
            return val
        elif op in ":":
            op2 = int(self.evaluateStack(s))
            op1 = int(self.evaluateStack(s))

            return slice(op1, op2, None)
        elif op in "[]":
            op1 = self.evaluateStack(s)
            ops = ()
            i = 0
            dims = len(s)
            while len(s) > 0:
                val = self.evaluateStack(s)
                if not isinstance(val, slice):
                    val = int(val)
                ops += val,
                i = i+1
            ops = ops[::-1]
            return op1[ops]
        elif op in "{}":
            op1 = self.evaluateStack(s)
            if self.ae:
                op2 = self.evaluateStack(s).astype(np.int64).values
                op2 = self.get_pqa_mask(op2)
            else:
                op2 = self.evaluateStack(s)

            val = xray.DataArray.where(op1, op2)
            return val
        elif op == "?":
            op1 = s.pop()
            op2 = s.pop()
            op3 = s.pop()

            ifval = self.evaluateStack(op1)
            if ifval:
                return self.evaluateStack(op2)
            else:
                return self.evaluateStack(op3)
        elif op[0].isalpha():
            if self.local_dict is not None and op in self.local_dict:
                return self.local_dict[op]
            frame = self.getframe(op)
            if op in frame.f_locals:
                return frame.f_locals[op]
            if op in frame.f_globals:
                return frame.f_globals[op]
        else:
            return float(op)

    def is_number(self, s):
        try:
            float(s)
            return True
        except ValueError:
            return False

    def flatten_list(self, l):
        return [item for sublist in l for item in sublist]

    def getframe(self, var):
        try:
            limit = sys.getrecursionlimit()
            for i in range(0, limit):
                frame = sys._getframe(i)
                if var in frame.f_locals or var in frame.f_globals:
                    return frame
            return self.f
        except ValueError:
            return self.f
    '''
    def evaluate(self, s):
        self.f = sys._getframe(1)
        self.exprStack = []
        results = self.parser.parseString(s)
        #print(self.exprStack)
        val = self.evaluateStack(self.exprStack[:])
        return val

    def evaluate(self, s, local_dict):
        self.local_dict = local_dict
        self.exprStack = []
        results = self.parser.parseString(s)
        #print(self.exprStack)
        val = self.evaluateStack(self.exprStack[:])
        return val
    '''
    def evaluate(self, s, local_dict=None):
        if local_dict is None:
            self.local_dict = None
            self.f = sys._getframe(1)
        else:
            self.f = None
            self.local_dict = local_dict
        self.exprStack = []
        results = self.parser.parseString(s)
        #print(self.exprStack)
        val = self.evaluateStack(self.exprStack[:])
        return val

    def test(self, s, e):
        result = self.evaluate(s)
        self.f = sys._getframe(1)
        if isinstance(result, int) or isinstance(result, float) or \
           isinstance(result, np.float64):
            r = e == result
        else:
            r = e.equals(result)
        if r:
            print(s, "=", r)
            return True
        else:
            print(s, "=", r, " ****** FAILED ******")
            return False

    def get_pqa_mask(self, pqa_ndarray,
                     good_pixel_masks=[32767, 16383, 2457], dilation=3):
        '''
        create pqa_mask from a ndarray

        Parameters:
            pqa_ndarray: input pqa array
            good_pixel_masks: known good pixel values
            dilation: amount of dilation to apply
        '''

        pqa_mask = np.zeros(pqa_ndarray.shape, dtype=np.bool)
        for i in range(len(pqa_ndarray)):
            pqa_array = pqa_ndarray[i]
            # Ignore bit 6 (saturation for band 62) - always 0 for Landsat 5
            pqa_array = pqa_array | 64

            # Dilating both the cloud and cloud shadow masks
            s = [[1, 1, 1], [1, 1, 1], [1, 1, 1]]
            acca = (pqa_array & 1024) >> 10
            erode = ndimage.binary_erosion(acca, s, iterations=dilation,
                                           border_value=1)
            dif = erode - acca
            dif[dif < 0] = 1
            pqa_array += (dif << 10)
            del acca
            fmask = (pqa_array & 2048) >> 11
            erode = ndimage.binary_erosion(fmask, s, iterations=dilation,
                                           border_value=1)
            dif = erode - fmask
            dif[dif < 0] = 1
            pqa_array += (dif << 11)
            del fmask
            acca_shad = (pqa_array & 4096) >> 12
            erode = ndimage.binary_erosion(acca_shad, s, iterations=dilation,
                                           border_value=1)
            dif = erode - acca_shad
            dif[dif < 0] = 1
            pqa_array += (dif << 12)
            del acca_shad
            fmask_shad = (pqa_array & 8192) >> 13
            erode = ndimage.binary_erosion(fmask_shad, s, iterations=dilation,
                                           border_value=1)
            dif = erode - fmask_shad
            dif[dif < 0] = 1
            pqa_array += (dif << 13)

            for good_pixel_mask in good_pixel_masks:
                pqa_mask[i][pqa_array == good_pixel_mask] = True
        return pqa_mask

    def plot3D(self, array_result):
        print('plot3D')

        img = array_result
        num_t = img.shape[0]
        num_rowcol = math.ceil(math.sqrt(num_t))
        fig = plt.figure(1)
        fig.clf()
        plot_count = 1
        for i in range(img.shape[0]):
            data = img[i]
            # data[data == -999] = 0
            ax = fig.add_subplot(num_rowcol, num_rowcol, plot_count)
            cax = ax.imshow(data, interpolation='nearest', aspect='equal')
            plot_count += 1
        fig.tight_layout()
        plt.subplots_adjust(wspace=0.5, hspace=0.5)
        plt.show()

    def test_1_level(self):
        x5 = xray.DataArray(np.random.randn(2, 3))
        self.evaluate("z5 = x5 + 1")
        print(z5)

    def test_2_level(self):
        self.test_2_level_fn()

    def test_2_level_fn(self):
        x6 = xray.DataArray(np.random.randn(2, 3))
        self.evaluate("z6 = x6 + 1")
        print(z6)

    def test2(self):
        x1 = xray.DataArray(np.random.randn(2, 3))
        y1 = xray.DataArray(np.random.randn(2, 3))
        z1 = xray.DataArray(np.array([[[0,  1,  2], [3,  4,  5], [6,  7,  8]],
                                     [[9, 10, 11], [12, 13, 14], [15, 16, 17]],
                                     [[18, 19, 20], [21, 22, 23], [24, 25, 26]]
                                      ]))
        z2 = z1*2
        z3 = np.arange(27)
        mask1 = z1 > 4

        ne = NDexpr()

        '''
        print "x1 = ", x1
        print "y1 = ", y1
        '''

        ne.test("angle(z1)", xray.ufuncs.angle(z1))
        ne.test("arccos(z1)", xray.ufuncs.arccos(z1))
        ne.test("arccosh(z1)", xray.ufuncs.arccosh(z1))
        ne.test("arcsin(z1)", xray.ufuncs.arcsin(z1))
        ne.test("arcsinh(z1)", xray.ufuncs.arcsinh(z1))
        ne.test("arctan(z1)", xray.ufuncs.arctan(z1))
        ne.test("arctanh(z1)", xray.ufuncs.arctanh(z1))
        ne.test("ceil(z1)", xray.ufuncs.ceil(z1))
        ne.test("conj(z1)", xray.ufuncs.conj(z1))
        ne.test("cos(z1)", xray.ufuncs.cos(z1))
        ne.test("cosh(z1)", xray.ufuncs.cosh(z1))
        ne.test("deg2rad(z1)", xray.ufuncs.deg2rad(z1))
        ne.test("degrees(z1)", xray.ufuncs.degrees(z1))
        ne.test("exp(z1)", xray.ufuncs.exp(z1))
        ne.test("expm1(z1)", xray.ufuncs.expm1(z1))
        ne.test("fabs(z1)", xray.ufuncs.fabs(z1))
        ne.test("fix(z1)", xray.ufuncs.fix(z1))
        ne.test("floor(z1)", xray.ufuncs.floor(z1))
        ne.test("frexp(z3)", xray.DataArray(xray.ufuncs.frexp(z3)))
        ne.test("imag(z1)", xray.ufuncs.imag(z1))
        ne.test("iscomplex(z1)", xray.ufuncs.iscomplex(z1))
        ne.test("isfinite(z1)", xray.ufuncs.isfinite(z1))
        ne.test("isinf(z1)", xray.ufuncs.isinf(z1))
        ne.test("isnan(z1)", xray.ufuncs.isnan(z1))
        ne.test("isreal(z1)", xray.ufuncs.isreal(z1))
        ne.test("log(z1)", xray.ufuncs.log(z1))
        ne.test("log10(z1)", xray.ufuncs.log10(z1))
        ne.test("log1p(z1)", xray.ufuncs.log1p(z1))
        ne.test("log2(z1)", xray.ufuncs.log2(z1))
        ne.test("rad2deg(z1)", xray.ufuncs.rad2deg(z1))
        ne.test("radians(z1)", xray.ufuncs.radians(z1))
        ne.test("real(z1)", xray.ufuncs.real(z1))
        ne.test("rint(z1)", xray.ufuncs.rint(z1))
        ne.test("sign(z1)", xray.ufuncs.sign(z1))
        ne.test("signbit(z1)", xray.ufuncs.signbit(z1))
        ne.test("sin(z1)", xray.ufuncs.sin(z1))
        ne.test("sinh(z1)", xray.ufuncs.sinh(z1))
        ne.test("sqrt(z1)", xray.ufuncs.sqrt(z1))
        ne.test("square(z1)", xray.ufuncs.square(z1))
        ne.test("tan(z1)", xray.ufuncs.tan(z1))
        ne.test("tanh(z1)", xray.ufuncs.tanh(z1))
        ne.test("trunc(z1)", xray.ufuncs.trunc(z1))

        ne.test("arctan2(z1, z2)", xray.ufuncs.arctan2(z1, z2))
        ne.test("copysign(z1, z2)", xray.ufuncs.copysign(z1, z2))
        ne.test("fmax(z1, z2)", xray.ufuncs.fmax(z1, z2))
        ne.test("fmin(z1, z2)", xray.ufuncs.fmin(z1, z2))
        ne.test("fmod(z1, z2)", xray.ufuncs.fmod(z1, z2))
        ne.test("hypot(z1, z2)", xray.ufuncs.hypot(z1, z2))
        ne.test("ldexp(z1, z2)", xray.DataArray(xray.ufuncs.ldexp(z1, z2)))
        ne.test("logaddexp(z1, z2)", xray.ufuncs.logaddexp(z1, z2))
        ne.test("logaddexp2(z1, z2)", xray.ufuncs.logaddexp2(z1, z2))
        ne.test("logicaland(z1, z2)", xray.ufuncs.logical_and(z1, z2))
        ne.test("logicalnot(z1, z2)", xray.ufuncs.logical_not(z1, z2))
        ne.test("logicalor(z1, z2)", xray.ufuncs.logical_or(z1, z2))
        ne.test("logicalxor(z1, z2)", xray.ufuncs.logical_xor(z1, z2))
        ne.test("maximum(z1, z2)", xray.ufuncs.maximum(z1, z2))
        ne.test("minimum(z1, z2)", xray.ufuncs.minimum(z1, z2))
        ne.test("nextafter(z1, z2)", xray.ufuncs.nextafter(z1, z2))

        ne.test("all(z1)", xray.DataArray.all(z1))
        ne.test("all(z1, 0)", xray.DataArray.all(z1, axis=0))
        ne.test("all(z1, 0, 1)", xray.DataArray.all(z1, axis=(0, 1)))
        ne.test("all(z1, 0, 1, 2)", xray.DataArray.all(z1, axis=(0, 1, 2)))

        ne.test("any(z1)", xray.DataArray.any(z1))
        ne.test("any(z1, 0)", xray.DataArray.any(z1, axis=0))
        ne.test("any(z1, 0, 1)", xray.DataArray.any(z1, axis=(0, 1)))
        ne.test("any(z1, 0, 1, 2)", xray.DataArray.any(z1, axis=(0, 1, 2)))

        ne.test("argmax(z1)", xray.DataArray.argmax(z1))
        ne.test("argmax(z1, 0)", xray.DataArray.argmax(z1, axis=0))
        ne.test("argmax(z1, 1)", xray.DataArray.argmax(z1, axis=1))
        ne.test("argmax(z1, 2)", xray.DataArray.argmax(z1, axis=2))

        ne.test("argmin(z1)", xray.DataArray.argmin(z1))
        ne.test("argmin(z1, 0)", xray.DataArray.argmin(z1, axis=0))
        ne.test("argmin(z1, 1)", xray.DataArray.argmin(z1, axis=1))
        ne.test("argmin(z1, 2)", xray.DataArray.argmin(z1, axis=2))

        ne.test("max(z1)", xray.DataArray.max(z1))
        ne.test("max(z1, 0)", xray.DataArray.max(z1, axis=0))
        ne.test("max(z1, 0, 1)", xray.DataArray.max(z1, axis=(0, 1)))
        ne.test("max(z1, 0, 1, 2)", xray.DataArray.max(z1, axis=(0, 1, 2)))

        ne.test("mean(z1)", xray.DataArray.mean(z1))
        ne.test("mean(z1, 0)", xray.DataArray.mean(z1, axis=0))
        ne.test("mean(z1, 0, 1)", xray.DataArray.mean(z1, axis=(0, 1)))
        ne.test("mean(z1, 0, 1, 2)", xray.DataArray.mean(z1, axis=(0, 1, 2)))

        ne.test("median(z1)", xray.DataArray.median(z1))
        ne.test("median(z1, 0)", xray.DataArray.median(z1, axis=0))
        ne.test("median(z1, 0, 1)", xray.DataArray.median(z1, axis=(0, 1)))
        ne.test("median(z1, 0, 1, 2)", xray.DataArray.median(z1, axis=(0, 1, 2)
                                                             ))

        ne.test("min(z1)", xray.DataArray.min(z1))
        ne.test("min(z1, 0)", xray.DataArray.min(z1, axis=0))
        ne.test("min(z1, 0, 1)", xray.DataArray.min(z1, axis=(0, 1)))
        ne.test("min(z1, 0, 1, 2)", xray.DataArray.min(z1, axis=(0, 1, 2)))

        ne.test("prod(z1)", xray.DataArray.prod(z1))
        ne.test("prod(z1, 0)", xray.DataArray.prod(z1, axis=0))
        ne.test("prod(z1, 0, 1)", xray.DataArray.prod(z1, axis=(0, 1)))
        ne.test("prod(z1, 0, 1, 2)", xray.DataArray.prod(z1, axis=(0, 1, 2)))

        ne.test("sum(z1)", xray.DataArray.sum(z1))
        ne.test("sum(z1, 0)", xray.DataArray.sum(z1, axis=0))
        ne.test("sum(z1, 0, 1)", xray.DataArray.sum(z1, axis=(0, 1)))
        ne.test("sum(z1, 0, 1, 2)", xray.DataArray.sum(z1, axis=(0, 1, 2)))

        ne.test("std(z1)", xray.DataArray.std(z1))
        ne.test("std(z1, 0)", xray.DataArray.std(z1, axis=0))
        ne.test("std(z1, 0, 1)", xray.DataArray.std(z1, axis=(0, 1)))
        ne.test("std(z1, 0, 1, 2)", xray.DataArray.std(z1, axis=(0, 1, 2)))

        ne.test("var(z1)", xray.DataArray.var(z1))
        ne.test("var(z1, 0)", xray.DataArray.var(z1, axis=0))
        ne.test("var(z1, 0, 1)", xray.DataArray.var(z1, axis=(0, 1)))
        ne.test("var(z1, 0, 1, 2)", xray.DataArray.var(z1, axis=(0, 1, 2)))

        ne.test("percentile(z1, 50)", np.percentile(z1, 50))
        ne.test("percentile(z1, 50)+percentile(z1, 50)",
                np.percentile(z1, 50) + np.percentile(z1, 50))
        ne.test("1 + var(z1, 0, 0+1, 2) + 1",
                1+xray.DataArray.var(z1, axis=(0, 0+1, 2))+1)

        ne.test("z1{mask1}", xray.DataArray.where(z1, mask1))
        ne.test("z1{z1>2}", xray.DataArray.where(z1, z1 > 2))
        ne.test("z1{z1>=2}", xray.DataArray.where(z1, z1 >= 2))
        ne.test("z1{z1<2}", xray.DataArray.where(z1, z1 < 2))
        ne.test("z1{z1<=2}", xray.DataArray.where(z1, z1 <= 2))
        ne.test("z1{z1==2}", xray.DataArray.where(z1, z1 == 2))
        ne.test("z1{z1!=2}", xray.DataArray.where(z1, z1 != 2))

        ne.test("z1{z1<2 | z1>5}", xray.DataArray.where(z1, (z1 < 2) | (z1 > 5)
                                                        ))
        ne.test("z1{z1>2 & z1<5}", xray.DataArray.where(z1, (z1 > 2) & (z1 < 5)
                                                        ))

        ne.evaluate("m = z1+1")
        ne.test("m", z1+1)

        ne.test("z1{~mask1}", xray.DataArray.where(z1, ~mask1))

        print(ne.evaluate("(1<0?1+1;2+2)"))
        print(ne.evaluate("(1<2?z1+1;2+2)"))
        ne.test("z1+mask1", xray.DataArray.where(z1, mask1))
