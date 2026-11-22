"""The ctypes signature table of the WGFMU binding against the API extract (blueprint v2 2.4 "argtypes/restype for
every used function generated from references/manuals/structured/b1530a-wgfmu-api-reference.yaml (checked by a unit
test against the YAML)"; WP10.2).

``C_SIGNATURES`` in ``transport/wgfmu/dll.py`` is the output of ``scripts/gen_wgfmu_signatures.py``; these tests
regenerate it, check it covers exactly ``api.C_FUNCTIONS``, that every function is documented in the extract with
matching parameter base types, that the prototypes are the manual's (Ed. 5 pages the extract cites, and Ed. 8), and
that the generator refuses inconsistent inputs."""

from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest
import yaml

from b1500_test_agent.transport.wgfmu import api, dll
from b1500_test_agent.transport.wgfmu.dll import C_SIGNATURES, argtypes_of
from tests.wgfmu_abi.fake_lib import ctype_name

pytestmark = pytest.mark.wgfmu

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "gen_wgfmu_signatures.py"
API_YAML = ROOT / "references" / "manuals" / "structured" / "b1530a-wgfmu-api-reference.yaml"


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gen_wgfmu_signatures", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


gen = _load_generator()


@pytest.fixture(scope="module")
def corpus():
    return gen._corpus()


@pytest.fixture(scope="module")
def items() -> list[dict]:
    return gen.load_items()


def test_the_committed_table_is_the_generated_one(corpus, items) -> None:
    assert gen.build(items, corpus) == C_SIGNATURES
    source = gen.TARGET.read_text(encoding="utf-8")
    assert gen.splice(source, gen.render(C_SIGNATURES)) == source  # the block in dll.py is current
    assert gen.main(["--check"]) == 0


def test_the_table_binds_exactly_the_protocol_functions() -> None:
    used = {name for names in api.C_FUNCTIONS.values() for name in names}
    assert set(C_SIGNATURES) == used and len(C_SIGNATURES) == 34


def test_every_function_is_documented_with_matching_parameter_types(items) -> None:
    for name, signature in C_SIGNATURES.items():
        item = gen.item_for(name, items)
        allowed = gen.extract_bases(item)
        assert {gen._base(t) for t in signature} <= allowed, (name, signature, allowed)
        assert str(item.get("implementation_status")).startswith("documented"), name  # never "undocumented"


def test_prototypes_are_the_manuals(corpus) -> None:
    """Spot checks against the guide's Syntax lines, where the extract lists parameters in another order or folds
    variants together (WG p95 (4-25), p97 (4-27), p111-112 (4-41, 4-42), p117 (4-47), p125 (4-55))."""
    assert C_SIGNATURES["WGFMU_getChannelIds"] == ("int*", "int*")  # (int* result, int* size)
    assert C_SIGNATURES["WGFMU_getError"] == ("char*", "int*")  # (char* result, int* size)
    assert C_SIGNATURES["WGFMU_getMeasureValues"] == ("int", "int", "int*", "double*", "double*")
    assert C_SIGNATURES["WGFMU_getMeasureValueSize"] == ("int", "int*", "int*")  # (chanId, complete, total)
    assert C_SIGNATURES["WGFMU_getStatus"] == ("int*", "double*", "double*")
    assert C_SIGNATURES["WGFMU_addVectors"] == ("const char*", "double*", "double*", "int")
    assert C_SIGNATURES["WGFMU_setMeasureEvent"] == ("const char*", "const char*", "double", "int", "double",
                                                     "double", "int")
    ed8 = gen.prototypes(corpus, gen.CURRENT_DOC)
    assert all(gen.signature(ed8[name]) == signature for name, signature in C_SIGNATURES.items())


def test_argtypes_and_restype_map_to_ctypes() -> None:
    names = {name: [ctype_name(t) for t in argtypes_of(name)] for name in C_SIGNATURES}
    assert names["WGFMU_openSession"] == ["c_char_p"]
    assert names["WGFMU_getMeasureValues"] == ["c_int", "c_int", "LP_c_int", "LP_c_double", "LP_c_double"]
    assert names["WGFMU_doSelfTest"] == ["LP_c_int", "c_char_p", "LP_c_int"]
    assert names["WGFMU_setTimeout"] == ["c_double"] and names["WGFMU_execute"] == []
    assert ctype_name(dll.RESTYPE) == "c_int"
    assert set(dll.C_TYPES) == set(gen.C_TYPES)


def test_parameter_parsing() -> None:
    assert gen.parse_parameters("int chanId, const char* pattern, double count") == (
        ("int", "chanId"), ("const char*", "pattern"), ("double", "count"))
    assert gen.parse_parameters("int* result,\n char *detail, int* size") == (
        ("int*", "result"), ("char*", "detail"), ("int*", "size"))
    assert gen.parse_parameters("") == () and gen.parse_parameters("void") == ()
    with pytest.raises(gen.SignatureError, match="const char\\*\\*"):
        gen.parse_parameters("int chanId, const char** pattern")


def test_generator_refuses_an_undocumented_function(corpus, items) -> None:
    trimmed = [i for i in items if "WGFMU_getStatus" not in i["name"]]
    with pytest.raises(gen.SignatureError, match="WGFMU_getStatus is not documented"):
        gen.build(trimmed, corpus)


def test_generator_refuses_a_base_type_the_extract_does_not_list(corpus, items) -> None:
    changed = copy.deepcopy(items)
    item = next(i for i in changed if i["name"] == "WGFMU_setTimeout")
    item["parameters"][0]["type"] = "int"  # the manual says double
    with pytest.raises(gen.SignatureError, match="WGFMU_setTimeout: parameter types \\['double'\\]"):
        gen.build(changed, corpus)


def test_generator_refuses_pages_without_the_prototype(corpus, items) -> None:
    changed = copy.deepcopy(items)
    item = next(i for i in changed if i["name"] == "WGFMU_openSession")
    item["pdf_pages"] = [2]
    with pytest.raises(gen.SignatureError, match="WGFMU_openSession: no prototype on WG5 pages \\[2\\]"):
        gen.build(changed, corpus)


def test_a_hand_edited_block_fails_the_check(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    copy_of = tmp_path / "dll.py"
    edited = dict(C_SIGNATURES, WGFMU_setTimeout=("int",))
    copy_of.write_text(gen.splice(gen.TARGET.read_text(encoding="utf-8"), gen.render(edited)), encoding="utf-8")
    monkeypatch.setattr(gen, "TARGET", copy_of)
    assert gen.main(["--check"]) == 1
    assert gen.main([]) == 0 and gen.main(["--check"]) == 0  # regenerated
    assert '"WGFMU_setTimeout": ("double",),' in copy_of.read_text(encoding="utf-8")


def test_the_extract_is_the_one_the_generator_reads() -> None:
    data = yaml.safe_load(API_YAML.read_text(encoding="utf-8"))
    assert data["source"]["edition"].startswith("Edition 5") and gen.EXTRACT_DOC == "WG5"
    assert gen.API_YAML == API_YAML
