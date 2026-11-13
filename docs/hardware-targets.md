# Hardware contracts

## Keep target identities separate

| Target | Contract and present scope |
| --- | --- |
| Logical PE | 32 input rows × 32 output columns in repository mapping/simulation; no physical fabric dimensions implied |
| Generic FABulous reference | Upstream reference-counter build and configured-fabric simulation |
| Experimental postprocessor | Separate 8×8 prototype, 384 LUT sites, 16 I/O bits and a 10 MHz requested clock; host-specific package excluded |
| ZCU106 Qwen6 | Pinned base overlay; signed int8 MVM with signed int32 outputs; current application applies bias/ReLU on the processor |
| SKY130 `classic_fabric_reram` | Concrete fabric, primitive maps, routing data and bitstream specification; upstream example compilation qualified, physical deployment unverified |

## SKY130 resources and pins

The pinned [upstream repository](https://github.com/mole99/sky130-reram-fpga/tree/e0790eb11a1e95914f2beb8f175396a0924144ed) advertises 2,160 LUT4+FF logic cells, 36 IOBUF, 36 RAM_32x4_2R_1W, 18 MACC_8x8_20, two RERAM_CIM_32x32, four GBUF and one SYS_RESET.

The `all[0]` through `all[27]` PCF entries map example signals onto specific I/O sites. They do not define total fabric I/O, available data-bus width or an accelerator transfer protocol. Clock/reset/enable allocations and board pin binding must be accounted for separately.

Generated RTL exposes 20 rows × 32 configuration data bits and 21 columns × 20 strobes. The adapter validates 420 frame headers, 8,400 payload words, a 35,304-byte stream, synchronization/desynchronization and byte-identical hex export. This validates file structure, not physical loading or functional behavior of a configured fabric.

The upstream routing command includes `--timing-allow-fail`. A counter run estimated 86.21 MHz and passed the tool's default 12 MHz check; this is a model-based timing estimate rather than board signoff. The ReRAM example leaves output pins unconstrained and holds its command input inactive. Successful compilation only establishes primitive mapping/configuration generation.

## X2 contracts

The candidate Wishbone behavioral implementation in Neuromorphic_X1 exposes `Neuromorphic_X2_wb`, selects address `0x3000000C` with full byte select, stores binary weights in a 32×32 array and consumes unsigned 8-bit compute values. It uses a 16-bit accumulator packed into a 32-bit result with a column identifier. The application's candidate regression uses `P=0` and reviewable private-copy fixes. This is not the same arithmetic or protocol as the ZCU106 overlay.

The ZCU106 driver uses AXI control and streamed/DMA data. Weights and activations are signed int8, results signed int32, dimensions up to 32×32. The adapter validates board identity and pinned overlay/driver hashes before execution. Stream packing, batch limits, row/column orientation and register definitions must match the exact driver revision.

The SKY130 ReRAM primitive has command/ready, result/ready, row/column addressing and PWM-related inputs. Do not infer a finalized host Wishbone register map from that primitive. Analog behavior, programming precision and host integration need their own qualified contract.

## Configuration and physical loading

Copy `deploy/physical-target.example.json` to an ignored local configuration only after installing a compatible board runtime and recording its actual hashes. `programming_enabled` defaults to false. The example cannot operate a board as supplied.

Never pass a SKY130 FABulous configuration to a Xilinx base-bitstream loader. The extension `.bit` does not establish compatibility. Likewise, the experimental AXI fabric loader is not a validated loader for this SKY130 target.

Outstanding work: board binding, validated clocks/timing corner, a tested target-specific configuration transport, finalized host protocol, generated tile RTL for full SKY130 simulation and numerical ReRAM tests. A1 must reject unknown capabilities rather than invent resource/precision assumptions.
