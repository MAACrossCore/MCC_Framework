namespace CommunityToolkit.Mvvm.ComponentModel
{
    public class ObservableObject { }
    [System.AttributeUsage(System.AttributeTargets.Field)]
    public class ObservablePropertyAttribute : System.Attribute { }
}
namespace MaaFramework.Binding
{
    public enum MaaJobStatus { Invalid, Failed, Succeeded }
    public class MaaJobStatusException : System.Exception { }
}
namespace Avalonia.Media
{
    public interface IBrush { }
    public static class Brushes { public static IBrush? OrangeRed => null; }
}
namespace MFAAvalonia.Extensions.MaaFW
{
    public class MaaProcessor
    {
        public const string ConnectionFailedAfterAllRetriesMessage = "connection failed";
        public string? InstanceId => null;
    }
}
namespace MFAAvalonia.ViewModels.Pages
{
    public class DragItemViewModel { }
    public class TaskQueueViewModel
    {
        public Extensions.MaaFW.MaaProcessor Processor { get; } = new();
        public void AddLogByKey(string key, Avalonia.Media.IBrush? brush, bool changeColor = false, bool transformKey = false, params string[] args) { }
        public void MarkTaskFailed(DragItemViewModel? item, long id, string? detail) { }
        public void MarkTaskRunning(DragItemViewModel? item, long id) { }
        public void MarkTaskStopped(DragItemViewModel? item, long id) { }
        public void MarkTaskSucceeded(DragItemViewModel? item, long id) { }
        public void MarkTaskIterationCompleted(DragItemViewModel? item, long id) { }
        public void SetCurrentTaskName(string name) { }
    }
}
namespace MFAAvalonia.Views.Windows { public class Placeholder { } }
namespace Serilog { public class Placeholder { } }
namespace MFAAvalonia.Helper
{
    public static class TelemetryService
    {
        public static void StartTask(string id, ValueType.MFATask task) { }
        public static void FinishTask(string id, ValueType.MFATask task, ValueType.MFATask.MFATaskStatus status, bool failed) { }
    }
    public static class LanguageHelper { public static string GetLocalizedString(string? name) => name ?? ""; }
    public static class LangKeys { public const string TaskStart = "start", TaskFailedWithName = "failed"; }
    public static class LoggerHelper
    {
        public static void Error(string message, System.Exception? ex = null) { }
        public static void Warning(string message) { }
    }
}
namespace MFAAvalonia.Helper.ValueType
{
    public partial class MFATask
    {
        public string? Name { get => _name; set => _name = value; }
        public MFATaskType Type { get => _type; set => _type = value; }
        public int Count { get => _count; set => _count = value; }
        public System.Func<System.Threading.Tasks.Task> Action { get => _action; set => _action = value; }
    }
}
