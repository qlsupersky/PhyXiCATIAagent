// Only the final return value enters model context.
const snapshots = [];
for (let i = 0; i < 2; i++) {
  const reply = await tools.native_modeling.modeling_status({});
  snapshots.push(reply.data.gate.status);
}
const busy = snapshots.filter(state => state !== 'IDLE');
return {ready: busy.length === 0, observed: snapshots, dispatchCAD: false};
