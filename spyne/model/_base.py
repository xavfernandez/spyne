
#
# spyne - Copyright (C) Spyne contributors.
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301
#

"""This module contains the ModelBase class and other building blocks for
defining models.
"""

import re

import spyne.const.xml_ns

from decimal import Decimal

from spyne.util import Break
from spyne.util.cdict import cdict
from spyne.util.odict import odict
from spyne.util.six import add_metaclass

from spyne.const.xml_ns import DEFAULT_NS


def _decode_pa_dict(d):
    """Decodes dict passed to prot_attrs.

    >>> _decode_pa_dict({})
    cdict({})
    >>> _decode_pa_dict({1: 2)})
    cdict({1: 2})
    >>> _decode_pa_dict({(1,2): 3)})
    cdict({1: 3, 2: 3})
    """

    retval = cdict()
    for k, v in d.items():
        if isinstance(k, tuple):
            for subk in k:
                retval[subk] = v

    for k, v in d.items():
        if not isinstance(k, tuple):
            retval[k] = v

    return retval


# All this code to get rid of a one letter quirk: nillable vs nullable.
class AttributesMeta(type(object)):
    NULLABLE_DEFAULT = True

    def __new__(cls, cls_name, cls_bases, cls_dict):
        # Mapper args should not be inherited.
        if not 'sqla_mapper_args' in cls_dict:
            cls_dict['sqla_mapper_args'] = None

        return super(AttributesMeta, cls).__new__(cls, cls_name, cls_bases, cls_dict)

    def __init__(self, cls_name, cls_bases, cls_dict):
        nullable = cls_dict.get('nullable', None)
        nillable = cls_dict.get('nillable', None)
        if nullable is not None:
            assert nillable is None or nullable == nillable
            self._nullable = nullable

        elif nillable is not None:
            assert nullable is None or nullable == nillable
            self._nullable = nillable

        if getattr(self, '_nullable', None) is None:
            self._nullable = None

        super(AttributesMeta, self).__init__(cls_name, cls_bases, cls_dict)

    def get_nullable(self):
        return (self._nullable if self._nullable is not None else
                self.NULLABLE_DEFAULT)

    def set_nullable(self, what):
        self._nullable = what

    nullable = property(get_nullable, set_nullable)

    def get_nillable(self):
        return self.nullable

    def set_nillable(self, what):
        self.nullable = what

    nillable = property(get_nillable, set_nillable)


class ModelBase(object):
    """The base class for type markers. It defines the model interface for the
    interface generators to use and also manages class customizations that are
    mainly used for defining constraints on input values.
    """

    __orig__ = None
    """This holds the original class the class .customize()d from. Ie if this is
    None, the class is not a customize()d one."""

    __extends__ = None
    """This holds the original class the class inherited or .customize()d from.
    This is different from __orig__ because it's only set when
    ``cls.is_default(cls) == False``"""

    __namespace__ = None
    """The public namespace of this class. Use ``get_namespace()`` instead of
    accessing it directly."""

    __type_name__ = None
    """The public type name of the class. Use ``get_type_name()`` instead of
    accessing it directly."""

    Value = type(None)
    """The value of this type is an instance of this class"""

    # These are not the xml schema defaults. The xml schema defaults are
    # considered in XmlSchema's add() method. the defaults here are to reflect
    # what people seem to want most.
    #
    # Please note that min_occurs and max_occurs must be validated in the
    # ComplexModelBase deserializer.
    @add_metaclass(AttributesMeta)
    class Attributes(object):
        """The class that holds the constraints for the given type."""

        _wrapper = False
        # when skip_wrappers=True is passed to a protocol, these objects
        # are skipped. just for internal use.

        default = None
        """The default value if the input is None"""

        default_factory = None
        """The default value if the input is None"""

        nillable = None
        """Set this to false to reject null values. Synonyms with
        ``nullable``. True by default. The default value can be changed by
         setting ``AttributesMeta.NULLABLE_DEFAULT``."""

        min_occurs = 0
        """Set this to 1 to make this object mandatory. Can be set to any
        positive integer. Note that an object can still be null or empty, even
        if it's there."""

        max_occurs = 1
        """Can be set to any strictly positive integer. Values greater than 1
        will imply an iterable of objects as native python type. Can be set to
        ``decimal.Decimal("inf")`` for arbitrary number of arguments."""

        schema_tag = '{%s}element' % spyne.const.xml_ns.xsd
        """The tag used to add a primitives as child to a complex type in the
        xml schema."""

        translations = None
        """A dict that contains locale codes as keys and translations of field
        names to that language as values.
        """

        sub_ns = None
        """An Xml-specific attribute that specifies which namespace should be
        used for field names in classes.
        """

        sub_name = None
        """This specifies which string should be used as field name when this
        type is seriazed under a ComplexModel.
        """

        sqla_column_args = None
        """A dict that will be passed to SQLAlchemy's ``Column`` constructor as
        ``**kwargs``.
        """

        exc_mapper = False
        """If true, this field will be excluded from the table mapper of the
        parent class.
        """

        exc_table = False
        """If true, this field will be excluded from the table of the parent
        class.
        """

        exc_interface = False
        """If true, this field will be excluded from the interface document."""

        logged = True
        """If false, this object will be ignored in ``log_repr``, mostly used
        for logging purposes."""

        unique = None
        """If True, this object will be set as unique in the database schema
        with default indexing options. If the value is a string, it will be
        used as the indexing method to create the unique index. See sqlalchemy
        documentation on how to create multi-column unique constraints.
        """

        db_type = None
        """When not None, it overrides Spyne's own mapping from Spyne types to
        SQLAlchemy types. It's a standard SQLAlchemy type marker, e.g.
        ``sqlalchemy.Integer``.
        """

        table_name = None
        """Database table name."""

        xml_choice_group = None
        """When not None, shares the same <choice> tag with fields with the same
        xml_choice_group value.
        """

        index = None
        """Can be ``True``, a string, or a tuple of two strings.

        * If True, this object will be set as indexed in the database schema
          with default options.

        * If the value is a string, the value will denote the indexing method
          used by the database. See: http://www.postgresql.org/docs/9.2/static/indexes-types.html

        * If the vale is a tuple of two strings, the first value will denote the
          index name and the second value will denote the indexing method as
          above.
        """

        read_only= False
        """If True, the attribute won't be initialized from outside values."""

        prot_attrs = None
        """to be implemented."""
        #"""Customize child attributes for protocols. It's a dict of dicts.
        #The key is either a ProtocolBase subclass or a ProtocolBase instance.
        #Instances override classes."""

        pa = None
        """Alias for prot_attrs."""

        empty_is_none = False
        """When the incoming object is empty (e.g. '' for strings) treat it as
        None. No effect (yet) for outgoing values."""

        order = None
        """An integer that's passed to ``_type_info.insert()`` as first argument
         when not None. ``.append()`` is used otherwise."""

    class Annotations(object):
        """The class that holds the annotations for the given type."""

        __use_parent_doc__ = False
        """If set to True Annotations will use __doc__ from parent,
        This is a convenience option"""

        doc = ""
        """The public documentation for the given type."""

        appinfo = None
        """Any object that carries app-specific info."""

    class Empty(object):
        pass

    _force_own_namespace = None

    @staticmethod
    def is_default(cls):
        return True

    @classmethod
    def get_namespace_prefix(cls, interface):
        """Returns the namespace prefix for the given interface. The
        get_namespace_prefix of the interface class generates a prefix if none
        is defined.
        """

        ns = cls.get_namespace()

        retval = interface.get_namespace_prefix(ns)

        return retval

    @classmethod
    def get_namespace(cls):
        """Returns the namespace of the class. Defaults to the python module
        name."""

        return cls.__namespace__

    # TODO: rename to "resolve_identifier"
    @staticmethod
    def resolve_namespace(cls, default_ns, tags=None):
        """This call finalizes the namespace assignment. The default namespace
        is not available until the application calls populate_interface method
        of the interface generator.
        """

        if tags is None:
            tags = set()
        elif cls in tags:
            return False
        tags.add(cls)

        if cls.__namespace__ is spyne.const.xml_ns.DEFAULT_NS:
            cls.__namespace__ = default_ns

        if (cls.__namespace__ in spyne.const.xml_ns.const_prefmap and
                                                       not cls.is_default(cls)):
            cls.__namespace__ = default_ns

        if cls.__namespace__ is None:
            ret = []
            for f in cls.__module__.split('.'):
                if f.startswith('_'):
                    break
                else:
                    ret.append(f)

            cls.__namespace__ = '.'.join(ret)

        if cls.__namespace__ is None or len(cls.__namespace__) == 0:
            cls.__namespace__ = default_ns

        if cls.__namespace__ is None or len(cls.__namespace__) == 0:
            raise ValueError("You need to explicitly set %r.__namespace__" % cls)

        if getattr(cls, '__extends__', None) != None:
            cls.__extends__.resolve_namespace(cls.__extends__, default_ns, tags)

        return True

    @classmethod
    def get_type_name(cls):
        """Returns the class name unless the __type_name__ attribute is defined.
        """

        retval = cls.__type_name__
        if retval is None:
            retval = cls.__name__

        return retval

    # FIXME: Rename this to get_type_name_with_ns_pref
    @classmethod
    def get_type_name_ns(cls, interface):
        """Returns the type name with a namespace prefix, separated by a column.
        """

        if cls.get_namespace() != None:
            return "%s:%s" % (cls.get_namespace_prefix(interface),
                                                            cls.get_type_name())

    @classmethod
    def get_element_name(cls):
        return cls.Attributes.sub_name or cls.get_type_name()

    @classmethod
    def get_element_name_ns(cls, interface):
        ns = cls.Attributes.sub_ns or cls.get_namespace()
        if ns is DEFAULT_NS:
            ns = interface.get_tns()
        if ns is not None:
            pref = interface.get_namespace_prefix(ns)
            return "%s:%s" % (pref, cls.get_element_name())

    @classmethod
    def to_string(cls, value):
        """
        Returns str(value). This should be overridden if this is not enough.
        """
        return str(value)

    @classmethod
    def to_unicode(cls, value):
        """
        Returns unicode(value). This should be overridden if this is not enough.
        """
        return unicode(value)

    @classmethod
    def customize(cls, **kwargs):
        """Duplicates cls and overwrites the values in ``cls.Attributes`` with
        ``**kwargs`` and returns the new class."""

        cls_name, cls_bases, cls_dict = cls._s_customize(cls, **kwargs)

        return type(cls_name, cls_bases, cls_dict)

    @staticmethod
    def _s_customize(cls, **kwargs):
        """This function duplicates and customizes the class it belongs to. The
        original class remains unchanged.

        Not meant to be overridden.
        """

        cls_dict = odict({'__module__': cls.__module__})

        if getattr(cls, '__orig__', None) is None:
            cls_dict['__orig__'] = cls

        class Attributes(cls.Attributes):
            pass

        if cls.Attributes.translations is None:
            Attributes.translations = {}
        if cls.Attributes.sqla_column_args is None:
            Attributes.sqla_column_args = (), {}

        cls_dict['Attributes'] = Attributes

        # as nillable is a property, it gets reset everytime a new class is
        # defined. So we need to reinitialize it explicitly.
        Attributes.nillable = cls.Attributes.nillable

        class Annotations(cls.Annotations):
            pass
        cls_dict['Annotations'] = Annotations

        for k, v in kwargs.items():
            if k.startswith('_'):
                continue

            elif k in ("doc", "appinfo"):
                setattr(Annotations, k, v)

            elif k in ('primary_key', 'pk'):
                Attributes.sqla_column_args[-1]['primary_key'] = v

            elif k in ('prot_attrs', 'pa'):
                setattr(Attributes, 'prot_attrs', _decode_pa_dict(v))

            elif k in ('foreign_key', 'fk'):
                from sqlalchemy.schema import ForeignKey
                t, d = Attributes.sqla_column_args
                fkt = (ForeignKey(v),)
                Attributes.sqla_column_args = (t + fkt, d)

            elif k in ('autoincrement', 'onupdate', 'server_default'):
                Attributes.sqla_column_args[-1][k] = v

            elif k == 'max_occurs' and v in ('unbounded', 'inf', float('inf')):
                setattr(Attributes, k, Decimal('inf'))

            else:
                setattr(Attributes, k, v)

        return (cls.__name__, (cls,), cls_dict)

    @staticmethod
    def validate_string(cls, value):
        """Override this method to do your own input validation on the input
        string. This is called before converting the incoming string to the
        native python value."""

        return (cls.Attributes.nillable or value is not None)

    @staticmethod
    def validate_native(cls, value):
        """Override this method to do your own input validation on the native
        value. This is called after converting the incoming string to the
        native python value."""

        return (cls.Attributes.nullable or value is not None)


class Null(ModelBase):
    pass


class SimpleModelAttributesMeta(AttributesMeta):
    def __init__(self, cls_name, cls_bases, cls_dict):
        super(SimpleModelAttributesMeta, self).__init__(cls_name, cls_bases, cls_dict)
        if getattr(self, '_pattern', None) is None:
            self._pattern = None

    def get_pattern(self):
        return self._pattern

    def set_pattern(self, pattern):
        self._pattern = pattern
        if pattern is not None:
            self._pattern_re = re.compile(pattern)

    pattern = property(get_pattern, set_pattern)

    def get_unicode_pattern(self):
        return self._pattern

    def set_unicode_pattern(self, pattern):
        self._pattern = pattern
        if pattern is not None:
            self._pattern_re = re.compile(pattern, re.UNICODE)

    unicode_pattern = property(get_unicode_pattern, set_unicode_pattern)
    upattern = property(get_unicode_pattern, set_unicode_pattern)


class SimpleModel(ModelBase):
    """The base class for primitives."""

    __namespace__ = "http://www.w3.org/2001/XMLSchema"

    @add_metaclass(SimpleModelAttributesMeta)
    class Attributes(ModelBase.Attributes):
        """The class that holds the constraints for the given type."""

        values = set()
        """The set of possible values for this type."""

        _pattern_re = None

    def __new__(cls, **kwargs):
        """Overriden so that any attempt to instantiate a primitive will return
        a customized class instead of an instance.

        See spyne.model.base.ModelBase for more information.
        """

        return cls.customize(**kwargs)

    @classmethod
    def customize(cls, **kwargs):
        """Duplicates cls and overwrites the values in ``cls.Attributes`` with
        ``**kwargs`` and returns the new class."""

        cls_name, cls_bases, cls_dict = cls._s_customize(cls, **kwargs)

        retval = type(cls_name, cls_bases, cls_dict)

        if not retval.is_default(retval):
            retval.__extends__ = cls
            retval.__type_name__ = kwargs.get("type_name", ModelBase.Empty)

        retval.resolve_namespace(retval, kwargs.get('__namespace__'))

        return retval

    @staticmethod
    def is_default(cls):
        return (cls.Attributes.values == SimpleModel.Attributes.values)

    @staticmethod
    def validate_native(cls, value):
        return (     ModelBase.validate_native(cls, value)
                and (cls.Attributes.values is None or
                                            len(cls.Attributes.values) == 0 or (
                     (value is None     and cls.Attributes.nillable) or
                     (value is not None and value in cls.Attributes.values)
                ))
            )


class PushBase(object):
    def __init__(self, callback=None, errback=None):
        self._cb = callback
        self._eb = errback

        self.length = 0
        self.ctx = None
        self.app = None
        self.response = None
        self.gen = None
        self._cb_finish = None
        self._eb_finish = None

    def _init(self, ctx, response, gen, _cb_finish, _eb_finish):
        self.length = 0

        self.ctx = ctx
        self.app = ctx.app

        self.response = response
        self.gen = gen

        self._cb_finish = _cb_finish
        self._eb_finish = _eb_finish

    def init(self, ctx, response, gen, _cb_finish, _eb_finish):
        self._init(ctx, response, gen, _cb_finish, _eb_finish)
        if self._cb is not None:
            return self._cb(self)

    def __len__(self):
        return self.length

    def append(self, inst):
        self.gen.send(inst)
        self.length += 1

    def close(self):
        try:
            self.gen.throw(Break())
        except (Break, StopIteration, GeneratorExit):
            pass
        self._cb_finish()


class xml:
    """Compound option object for xml serialization. It's meant to be passed to
    :func:`ComplexModelBase.Attributes.store_as`.

    :param root_tag: Root tag of the xml element that contains the field values.
    :param no_ns: When true, the xml document is stripped from namespace
        information. This is generally a stupid thing to do. Use with caution.
    """

    def __init__(self, root_tag=None, no_ns=False, pretty_print=False):
        self.root_tag = root_tag
        self.no_ns = no_ns
        self.pretty_print = pretty_print


class table:
    """Compound option object for for storing the class instance as in row in a
    table in a relational database. It's meant to be passed to
    :func:`ComplexModelBase.Attributes.store_as`.

    :param multi: When False, configures a one-to-many relationship where the
        child table has a foreign key to the parent. When not ``False``,
        configures a many-to-many relationship by creating an intermediate
        relation table that has foreign keys to both parent and child classes
        and generates a table name automatically. When ``True``, the table name
        is generated automatically. Otherwise, it should be a string, as the
        value is used as the name of the intermediate table.
    :param left: Name of the left join column.
    :param right: Name of the right join column.
    :param backref: See http://docs.sqlalchemy.org/en/rel_0_9/orm/relationships.html#sqlalchemy.orm.relationship.params.backref
    :param cascade: See http://docs.sqlalchemy.org/en/rel_0_9/orm/relationships.html#sqlalchemy.orm.relationship.params.cascade
    :param lazy: See http://docs.sqlalchemy.org/en/rel_0_9/orm/relationships.html#sqlalchemy.orm.relationship.params.lazy
    :param back_populates: See http://docs.sqlalchemy.org/en/rel_0_9/orm/relationships.html#sqlalchemy.orm.relationship.params.back_populates
    """

    def __init__(self, multi=False, left=None, right=None, backref=None,
            id_backref=None, cascade=False, lazy='select', back_populates=None):
        self.multi = multi
        self.left = left
        self.right = right
        self.backref = backref
        self.id_backref = id_backref
        self.cascade = cascade
        self.lazy = lazy
        self.back_populates = back_populates


class json:
    """Compound option object for json serialization. It's meant to be passed to
    :func:`ComplexModelBase.Attributes.store_as`.

    Make sure you don't mix this with the json package when importing.
    """

    def __init__(self, ignore_wrappers=True, complex_as=dict):
        if ignore_wrappers != True:
            raise NotImplementedError("ignore_wrappers != True")
        self.ignore_wrappers = ignore_wrappers
        self.complex_as = complex_as


class msgpack:
    """Compound option object for msgpack serialization. It's meant to be passed
    to :func:`ComplexModelBase.Attributes.store_as`.

    Make sure you don't mix this with the msgpack package when importing.
    """
    def __init__(self):
        pass


def apply_pssm(val, pssm_map):
    if val is not None:
        val_c = pssm_map.get(val, None)
        if val_c is None:
            assert isinstance(val, tuple(pssm_map.values())), \
             "'store_as' should be one of: %r or an instance of %r not %r" \
             % (tuple(pssm_map.keys()), tuple(pssm_map.values()), val)

            return val
        return val_c()
