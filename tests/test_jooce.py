from enum import Enum

from jooce import gets, invoke, provides
from jooce.platform import TypeMetadata


def test_inject_identity():
    class Fuel(Enum):
        gas = "gas"
        electric = "electric"

    class Engine:
        pass

    @provides(Engine)
    @provides(Engine, Fuel.electric)
    class ElectricEngine(Engine):
        pass

    @provides(Engine, Fuel.gas)
    class GasEngine(Engine):
        pass

    def electric1(engine: Engine): return engine

    def electric2(engine: gets(Engine)): return engine

    def electric3(engine: gets(Engine, key = Engine)): return engine

    def electric4(engine: gets(Engine, key = Engine, tag = Fuel.electric)): return engine

    def electric5(engine: gets(Engine, tag = Fuel.electric)): return engine

    def gas1(engine: gets(Engine, tag = Fuel.gas)): return engine

    electric_engine = invoke(electric1)
    assert isinstance(electric_engine, ElectricEngine)

    assert electric_engine is invoke(electric2)
    assert electric_engine is invoke(electric3)
    assert electric_engine is invoke(electric4)
    assert electric_engine is invoke(electric5)

    gas_engine = invoke(gas1)
    assert isinstance(gas_engine, GasEngine)


def test_equal_metadata_share_single_annotation():
    def test1(obj: gets(object)): pass

    def test2(obj: gets(object)): pass

    container = TypeMetadata.container_for_arg(test1, "obj")
    assert TypeMetadata.container_for_arg(test2, "obj") is container
