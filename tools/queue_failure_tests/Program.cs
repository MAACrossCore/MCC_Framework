using MaaFramework.Binding;
using MFAAvalonia.Helper.ValueType;

static void Check(bool condition, string name)
{
    if (!condition) throw new Exception(name);
    Console.WriteLine("PASS: " + name);
}

int calls = 0;
var failure = new MFATask { Count = 10, ContinueOnError = true, MaaAction = () => { calls++; return Task.FromResult(MaaJobStatus.Failed); } };
var result = await failure.Run(CancellationToken.None);
Check(result.Status == MFATask.MFATaskStatus.FAILED && result.ContinueQueue, "ordinary failure continues queue");
Check(calls == 1, "failure ends remaining repetitions");
var next = new MFATask { MaaAction = () => Task.FromResult(MaaJobStatus.Succeeded) };
Check((await next.Run(CancellationToken.None)).Status == MFATask.MFATaskStatus.SUCCEEDED, "next task succeeds");
failure.ContinueOnError = false;
Check(!(await failure.Run(CancellationToken.None)).ContinueQueue, "initialization failure stops queue");
using var cancelled = new CancellationTokenSource();
cancelled.Cancel();
result = await failure.Run(cancelled.Token);
Check(result.Status == MFATask.MFATaskStatus.STOPPED && !result.ContinueQueue, "pre-cancel stops queue");
using var during = new CancellationTokenSource();
failure.ContinueOnError = true;
failure.MaaAction = () => { during.Cancel(); return Task.FromResult(MaaJobStatus.Failed); };
result = await failure.Run(during.Token);
Check(result.Status == MFATask.MFATaskStatus.STOPPED && !result.ContinueQueue, "stop during task overrides failure continuation");
failure.MaaAction = () => throw new InvalidOperationException("test failure");
result = await failure.Run(CancellationToken.None);
Check(result.Status == MFATask.MFATaskStatus.FAILED && result.ContinueQueue, "ordinary exception continues queue");
