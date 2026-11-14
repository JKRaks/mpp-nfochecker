import sys
import types
from pathlib import Path

package = types.ModuleType("nfocheck")
package.__path__ = [str(Path(__file__).resolve().parents[1] / "plugins.v3/nfocheck")]
sys.modules["nfocheck"] = package
