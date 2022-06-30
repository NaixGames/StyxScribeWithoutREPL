from weakref import WeakKeyDictionary
from numbers import Number
from collections import OrderedDict
from inspect import getmembers
from functools import wraps
from threading import local as thread_local
from types import MethodType

proxyTypes = dict()
marshallTypes = OrderedDict()
DELIM = '¦'

registry = None
lookup = None

NIL = None
Root = None

#https://stackoverflow.com/a/49013535
_meta_ignore = {"__repr__","__format__","__str__","__reduce__","__reduce_ex__","__sizeof__"}
_meta_inherited = {}
def _meta_wrap(name, method):
    local_flag = thread_local()
    @wraps(method)
    def wrapper(*args, **kw):
        local_method = method
        if not getattr(local_flag, "running", False) and args and not isinstance(args[0], type):
            local_flag.running = True
            # trigger __getattribute__:
            self = args[0]
            cls = self.__class__
            retrieved = cls.__getattribute__(self, name)
            if not retrieved is wrapper:
                local_method =  retrieved
            if isinstance(local_method, MethodType):
                args = args[1:]
        result = local_method(*args, **kw)
        local_flag.running = False
        return result
    wrapper._wrapped = True
    return wrapper
class MetaOverrider(type):
    def __init__(cls, name, bases, namespace, **kwd):
        super().__init__(name, bases, namespace, **kwd)
        
        global _meta_inherited
        d = None
        for c in cls.__mro__:
            if "Proxy" not in map(lambda _c: _c.__name__, c.__mro__):
                _cls = c
                d = inherited(_cls, cls)
                break
        _meta_inherited[cls] = d

        for name in dir(cls):
            if not (name.startswith("__") and name.endswith("__")):
                continue
            if name in ("__getattribute__", "__class__", "__init__"):
                continue
            if name in object.__dict__ and name not in _meta_ignore:
                continue
            if d is not None and name not in d:
                continue
            magic_method = getattr(cls, name)
            if not callable(magic_method) or getattr(magic_method, "_wrapped", False):
                continue
            setattr(cls, name, _meta_wrap(name, magic_method))

def nop():
    pass

def inherited(a,b):
    #https://stackoverflow.com/a/48281090
    a = dict(getmembers(a))
    b = dict(getmembers(b))
    return {k:v for k,v in b.items() if k in a and v == a[k]}

class _function():
    def __init__(self,call=None):
        if call is None:
            call = nop
        self.call = call
    def __call__(self,*args,**kwargs):
        return self.call(*args,**kwargs)
    def __repr__(self):
        return repr(self.call)

def notImplemented(self, *args, **kwargs):
    raise NotImplementedError(f"{type(self)} does not implement this operation")

def proxyType(cls):
    proxyTypes[cls.__name__] = cls
    return cls

def marshallType(*types):
    def f(cls):
        for t in types:
            mt = marshallTypes.get(cls,set())
            mt.add(t)
            marshallTypes[cls] = mt
        return cls
    return f

class Proxy(metaclass=MetaOverrider):
    def __init__(self, v=None, i=None):
        #initialise a new object to proxy, select from inheritance
        for cls in type(self).__mro__:
            if Proxy not in cls.__mro__:
                proxy = cls()
                break
        if i is None:
            i = id(self)
        self.proxy = proxy
        self.alive = True
        registry[i] = self
        lookup[self] = i
        self.root = i == 0
        self.local = i > 0
        if self.local:
            Scribe.Send(f"StyxScribeShared: New: {self.__class__.__name__}{DELIM}{i}")
        if v is not None:
            self._marshall(v)
    def __hash__(self):
        return hash(id(self))
    def __repr__(self):
        return repr(self.proxy)
    def __del__(self):
        i = lookup.get(self,None)
        if i is not None:
            self.alive = False
            try:
                del lookup[self]
            except KeyError:
                pass
            if i != 0:
                try:
                    del registry[i]
                except KeyError:
                    pass
                if self.local:
                    Scribe.Send(f"StyxScribeShared: Del: {i}")
    def __getattribute__(self, name):
        if name in _meta_inherited[type(self)]:
            proxy = object.__getattribute__(self, "proxy")
            try:
                attr = getattr(proxy, name)
                if callable(attr) and attr.__self__ == proxy:
                    def attr_wrapper(*args,**kwargs):
                        return attr(*args[1:],**kwargs)
                    return attr_wrapper
                return attr
            except AttributeError:
                pass
        return object.__getattribute__(self, name)       

class ProxySet(Proxy):
    def _shset(self, key, val):
        if self.alive:
            i = lookup[self]
            k = encode(key)
            v = encode(val)
            Scribe.Send(f"StyxScribeShared: Set: {i}{DELIM}{k}{DELIM}{v}")
    def __delitem__(self, key, sync=True):
        return self.__setitem__(key, NIL, sync)
    def __getitem__(self, key):
        try:
            return self.proxy[key]
        except KeyError:
            return NIL

class ProxyCall(Proxy):
    def _marshall(self, obj):
        if callable(obj):
            self.proxy = obj
        else:
            raise TypeError(f"{type(self)} cannot marshall type {type(obj)}")
    def _call(self, args):
        return self(*args)

@proxyType
@marshallType(dict, set)
class Table(ProxySet, dict):
    def _marshall(self, obj):
        if isinstance(obj, set):
            for k in obj:
                self[k] = True
        elif isinstance(obj, dict):
            for k,v in obj.items():
                self[k] = v
        else:
            raise TypeError(f"{type(self)} cannot marshall type {type(obj)}")
    def __setitem__(self, key, val, sync=True):
        key = marshall(key)
        if val is NIL:
            del self.proxy[key]
        else:
            val = marshall(val)
            self.proxy[key] = val
        if sync:
            self._shset(key, val)
    setdefault = notImplemented
    update = notImplemented
    pop = notImplemented
    popitem = notImplemented
    clear = notImplemented

@proxyType
@marshallType(list, tuple)
class Array(ProxySet, list):
    def _marshall(self, obj):
        enum = None
        try:
            enum = enumerate(obj)
        except TypeError:
            raise TypeError(f"{type(self)} cannot marshall type {type(obj)}")
        for k,v in enum:
            self[k] = v
    def __setitem__(self, key, val, sync=True):
        key = marshall(key)
        if val is NIL:
            d = key - len(self.proxy) + 1
            if d < 0:
                for i in range(d):
                    del self.proxy[-1]
            del self.proxy[key]
        else:
            if key > len(self.proxy):
                return
            val = marshall(val)
            if key == len(self.proxy):
                self.proxy.append(val)
            else:
                self.proxy[key] = val
        if sync:
            self._shset(key + 1, val)
    append = notImplemented
    extend = notImplemented
    insert = notImplemented
    remove = notImplemented
    sort = notImplemented
    reverse = notImplemented
    pop = notImplemented
    clear = notImplemented

@proxyType
class Args(Array):
    def __setitem__(self, key, val, sync=True):
        if val is NIL:
            if key >= len(self.proxy):
                return
            self.proxy[key] = NIL
        else:
            n = len(self.proxy)
            if key == 'n':
                val = marshall(val)
                if val >= n:
                    self.proxy.extend([NIL]*(val - n))
                if val < n:
                    self.proxy[::] = self.proxy[:val]
            else:
                key = marshall(key)
                val = marshall(val)
                if key > n:
                    self.proxy.extend([NIL]*(key - n)+[val])
                if key == len(self.proxy):
                    self.proxy.append(val)
                else:   
                    self.proxy[key] = val
        if sync:
            self._shset(key if key == 'n' else key + 1, val)
    def __getitem__(self, key):
        return self.proxy[key]

@proxyType
class KWArgs(Table):
    def __setitem__(self, key, val, sync=True):
        key = marshall(key)
        val = marshall(val)
        self.proxy[key] = val
        if sync:
            self._shset(key, val)
    def __getitem__(self, key):
        return self.proxy[key]

@proxyType
class Action(ProxyCall, _function):
    def __call__(self, *args):
        if self.local:
            self.proxy(*args)
        else:
            i = lookup[self]
            a = Args(args)
            ai = lookup[a]
            Scribe.Send(f"StyxScribeShared: Act: {i}{DELIM}{ai}")

@proxyType
@marshallType(_function)
class KWAction(Action):
    def __call__(self, *args, **kwargs):
        if self.local:
            self.proxy(*args, **kwargs)
        else:
            i = lookup[self]
            a = Args((KWArgs(kwargs), *args))
            ai = lookup[a]
            Scribe.Send(f"StyxScribeShared: Act: {i}{DELIM}{ai}")
    def _call(self, args):
        return self(*args[1:], **args[0])

def marshaller(obj):
    if isinstance(obj,Proxy):
        return None
    for c,ts in marshallTypes.items():
        for t in ts:
            if isinstance(obj,t):
                return c
            if callable(obj) and t is _function:
                return c
    return None

def marshall(obj):
    m = marshaller(obj)
    if m is not None:
        return m(obj)
    if isinstance(obj,str):
        return obj.replace(DELIM,':')
    if isinstance(obj,float):
        if float.is_integer(obj):
            return int(obj)
    return obj

def encode(v):
    if isinstance(v, bool):
        return "!!" if v else "!"
    if isinstance(v, str):
        return "&" + v
    if isinstance(v, Number):
        return "#" + str(v)
    if isinstance(v, Proxy):
        return "@" + str(lookup[v])
    if v is NIL:
        return "*"
    raise TypeError(f"{v} of type {type(v)} cannot be encoded.")

def decode(s):
    t = s[:1]
    v = s[1:]
    if t == "&":
        return v
    if t == "#":
        if v.isdigit():
            return int(v)
        return float(v)
    if t == "@":
        return registry[-int(v)]
    if t == "!":
        return v[0] == '!'
    if t == "*":
        return NIL
    raise TypeError(s + " cannot be decoded.")

def handleNew(message):
    t, i = message.split(DELIM)
    val = proxyTypes[t](None, -int(i))
    return val

def handleSet(message):
    i, k, v = message.split(DELIM)
    try:
        s = registry[-int(i)]
    except KeyError:
        return
    k = decode(k)
    if v[:1] == '&':
        v = v[:-1]
    v = decode(v)
    s.__setitem__(k, v, False)

def handleDel(message):
    i = -int(message)
    obj = registry.get(i,None)
    if obj is not None:
        obj.alive = False
        try:
            del lookup[obj]
        except KeyError:
            pass
        if i != 0:
            try:
                del registry[i]
            except KeyError:
                pass

def handleAct(message):
    func, args = message.split(DELIM)
    func = registry[-int(func)]
    args = registry[-int(args)]
    func._call(args)

def handleReset(message=None):
    global registry
    global lookup
    global Root
    if registry is not None:
        registry.clear()
    registry = {}
    if lookup is not None:
        lookup.clear()
    lookup = WeakKeyDictionary()
    Root = Table(None, 0)

def Load():
    Scribe.AddHook(handleReset, "StyxScribeShared: Reset", __name__)
    Scribe.AddHook(handleNew, "StyxScribeShared: New: ", __name__)
    Scribe.AddHook(handleSet, "StyxScribeShared: Set: ", __name__)
    Scribe.AddHook(handleDel, "StyxScribeShared: Del: ", __name__)
    Scribe.AddHook(handleAct, "StyxScribeShared: Act: ", __name__)
    #Scribe.IgnorePrefixes.append("StyxScribeShared: ")
