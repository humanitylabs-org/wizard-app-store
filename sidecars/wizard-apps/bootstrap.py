# Wizard apps sync bootstrap: python3 -c <this> <wizard_core.py> <hermes_adapter.py>
# Loads the two modules passed as arguments (sources: sidecars/wizard-apps/ in the Wizard App Store).
import sys, types
for name, source in (("wizard_core", sys.argv[1]), ("hermes_adapter", sys.argv[2])):
    module = types.ModuleType(name)
    module.__file__ = name + ".py"
    sys.modules[name] = module
    exec(compile(source, name + ".py", "exec"), module.__dict__)
sys.modules["hermes_adapter"].main()
