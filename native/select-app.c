/* Local IPP queue for the Select. PAPPL owns HTTP/IPP and raster decoding.
 * The Python worker owns image preparation, Bluetooth, and durable job claims.
 * No printer protocol or shell command is constructed here. */
#include <pappl/pappl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <fcntl.h>
#include <sys/stat.h>
#ifdef _WIN32
#  include <windows.h>
#  include <io.h>
#  define open _open
#  define close _close
#  define fdopen _fdopen
#  define O_BINARY _O_BINARY
#else
#  include <unistd.h>
#  include <sys/wait.h>
#  define O_BINARY 0
#endif

static const char *python_exe, *config_path, *jobs_dir;
static char state_path[2048];
typedef struct {
  FILE *file;
  char path[2048], key[37];
  unsigned pages, width, height, lines;
  bool failed, complete;
} select_job_t;

static bool save_state(pappl_system_t *system, void *data) {
  (void)data;
  return papplSystemSaveState(system, state_path);
}

static int run_worker(const char *path, const char *key, int quality) {
  char q[16];
  snprintf(q, sizeof(q), "%d", quality);
#ifdef _WIN32
  /* Windows filenames cannot contain quotes. Reject them before quoting args;
   * none of the final path arguments ends in a backslash. No shell is used. */
  char command[8192];
  wchar_t wide_command[8192], wide_python[2048];
  STARTUPINFOW startup;
  PROCESS_INFORMATION process;
  DWORD result = 1;
  if (strchr(python_exe, '"') || strchr(config_path, '"') || strchr(path, '"')) return 1;
  if (snprintf(command, sizeof(command), "\"%s\" -m zink_probe.ipp_worker --config \"%s\" --input \"%s\" --job-key %s --quality %s", python_exe, config_path, path, key, q) >= sizeof(command)) return 1;
  if (!MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, command, -1, wide_command, 8192) ||
      !MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, python_exe, -1, wide_python, 2048)) return 1;
  memset(&startup, 0, sizeof(startup)); startup.cb = sizeof(startup);
  memset(&process, 0, sizeof(process));
  if (!CreateProcessW(wide_python, wide_command, NULL, NULL, FALSE, CREATE_NO_WINDOW, NULL, NULL, &startup, &process)) return 1;
  if (WaitForSingleObject(process.hProcess, 360000) == WAIT_OBJECT_0)
    GetExitCodeProcess(process.hProcess, &result);
  else { TerminateProcess(process.hProcess, 3); result = 3; }
  CloseHandle(process.hThread); CloseHandle(process.hProcess);
  return (int)result;
#else
  pid_t pid = fork();
  int status;
  if (pid == 0) {
    execl(python_exe, python_exe, "-m", "zink_probe.ipp_worker", "--config", config_path,
          "--input", path, "--job-key", key, "--quality", q, (char *)NULL);
    _exit(127);
  }
  if (pid < 0 || waitpid(pid, &status, 0) != pid || !WIFEXITED(status)) return 1;
  return WEXITSTATUS(status);
#endif
}

static bool start_job(pappl_job_t *job, pappl_pr_options_t *options, pappl_device_t *device) {
  const char *uuid = ippGetString(papplJobGetAttribute(job, "job-uuid"), 0, NULL);
  select_job_t *data;
  size_t i;
  (void)device;
  if (papplJobGetCopies(job) != 1 || options->copies != 1 || options->num_pages > 1 ||
      papplJobGetNumberOfDocuments(job) > 1 || !uuid || strncmp(uuid, "urn:uuid:", 9) || strlen(uuid + 9) != 36) {
    papplJobSetMessage(job, "Select currently accepts one page and one copy per job.");
    return false;
  }
  uuid += 9;
  for (i = 0; i < 36; i++)
    if (!strchr("0123456789abcdefABCDEF-", uuid[i])) return false;
  data = calloc(1, sizeof(*data));
  if (!data) return false;
  cupsCopyString(data->key, uuid, sizeof(data->key));
  if (snprintf(data->path, sizeof(data->path), "%s/%s.rgb", jobs_dir, uuid) >= sizeof(data->path)) {
    free(data); return false;
  }
  papplJobSetData(job, data);
  return true;
}

static bool start_page(pappl_job_t *job, pappl_pr_options_t *options, pappl_device_t *device, unsigned page) {
  select_job_t *data = papplJobGetData(job);
  cups_page_header_t *h = &options->header;
  unsigned char header[12] = {'Z','R','G','B'};
  int fd;
  (void)device; (void)page;
  if (!data) return false;
  data->pages++;
  if (data->pages != 1 || h->cupsWidth == 0 || h->cupsHeight == 0 || h->cupsWidth > 4096 || h->cupsHeight > 4096 ||
      h->cupsBitsPerColor != 8 || h->cupsBitsPerPixel != 24 || h->cupsColorSpace != CUPS_CSPACE_SRGB ||
      h->cupsBytesPerLine != h->cupsWidth * 3 || h->cupsColorOrder != CUPS_ORDER_CHUNKED) {
    data->failed = true;
    papplJobSetMessage(job, "Expected one bounded 8-bit sRGB raster page; nothing was sent.");
    return false;
  }
  data->width = h->cupsWidth; data->height = h->cupsHeight;
  for (unsigned i = 0; i < 4; i++) {
    header[4+i] = (unsigned char)(data->width >> (24-i*8));
    header[8+i] = (unsigned char)(data->height >> (24-i*8));
  }
  fd = open(data->path, O_WRONLY | O_CREAT | O_EXCL | O_BINARY, 0600);
  if (fd < 0) { data->failed = true; return false; }
  data->file = fdopen(fd, "wb");
  if (!data->file) { close(fd); data->failed = true; return false; }
  if (fwrite(header, 1, 12, data->file) != 12) { data->failed = true; return false; }
  return true;
}

static bool write_line(pappl_job_t *job, pappl_pr_options_t *options, pappl_device_t *device, unsigned y, const unsigned char *line) {
  select_job_t *data = papplJobGetData(job);
  (void)options; (void)device;
  if (!data || !data->file || data->failed) return false;
  if (y != data->lines || y >= data->height || fwrite(line, 3, data->width, data->file) != data->width) {
    data->failed = true; return false;
  }
  data->lines++;
  return true;
}

static bool end_page(pappl_job_t *job, pappl_pr_options_t *options, pappl_device_t *device, unsigned page) {
  select_job_t *data = papplJobGetData(job);
  (void)options; (void)device; (void)page;
  if (!data || !data->file) return false;
  if (fclose(data->file)) data->failed = true;
  data->file = NULL;
  data->complete = data->lines == data->height && !data->failed;
  return data->complete;
}

static bool end_job(pappl_job_t *job, pappl_pr_options_t *options, pappl_device_t *device) {
  select_job_t *data = papplJobGetData(job);
  bool ok = false;
  (void)device;
  if (!data) return false;
  if (data->file) { fclose(data->file); data->failed = true; }
  if (!data->failed && data->complete && data->pages == 1 && !papplJobIsCanceled(job) && papplJobGetState(job) != IPP_JSTATE_ABORTED) {
    int result = run_worker(data->path, data->key, options->print_quality);
    ok = result == 0;
    papplJobSetMessage(job, ok ? "Select job processed; see the local job record." : "Select job stopped. Check its local record; do not blindly resend.");
  }
  free(data); papplJobSetData(job, NULL);
  return ok;
}

static bool device_open(pappl_device_t *device, const char *uri, pappl_job_t *job) {
  (void)device; (void)job; return !strcmp(uri, "zink://local");
}
static void device_close(pappl_device_t *device) { (void)device; }
static ssize_t device_read(pappl_device_t *device, void *buffer, size_t size) { (void)device; (void)buffer; (void)size; return -1; }
static ssize_t device_write(pappl_device_t *device, const void *buffer, size_t size) { (void)device; (void)buffer; (void)size; return -1; }
static bool printer_status(pappl_printer_t *printer) { (void)printer; return true; }

static bool driver(pappl_system_t *system, const char *name, const char *uri, const char *id, pappl_pr_driver_data_t *d, ipp_t **attrs, void *context) {
  (void)system; (void)name; (void)uri; (void)id; (void)attrs; (void)context;
  cupsCopyString(d->make_and_model, "HP Sprocket Select", sizeof(d->make_and_model));
  d->format = "image/pwg-raster";
  d->rstartjob_cb = start_job; d->rstartpage_cb = start_page;
  d->rwriteline_cb = write_line; d->rendpage_cb = end_page; d->rendjob_cb = end_job;
  d->status_cb = printer_status;
  d->raster_types = d->force_raster_type = PAPPL_RASTER_TYPE_SRGB_8;
  d->color_supported = d->color_default = PAPPL_COLOR_MODE_COLOR;
  d->copies_default = d->copies_supported = 1;
  d->quality_default = IPP_QUALITY_NORMAL;
  d->kind = PAPPL_KIND_PHOTO; d->ppm = d->ppm_color = 1;
  d->num_resolution = 1; d->x_resolution[0] = d->y_resolution[0] = d->x_default = d->y_default = 600;
  d->borderless = true; d->left_right = d->bottom_top = 0;
  d->num_media = 1; d->media[0] = "custom_58x87mm_58x87mm";
  cupsCopyString(d->media_default.size_name, d->media[0], sizeof(d->media_default.size_name));
  d->media_default.size_width = 5800; d->media_default.size_length = 8700;
  d->num_source = 1; d->source[0] = "main";
  cupsCopyString(d->media_default.source, "main", sizeof(d->media_default.source));
  cupsCopyString(d->media_default.type, "photographic", sizeof(d->media_default.type));
  d->media_ready[0] = d->media_default;
  d->num_type = 1; d->type[0] = "photographic";
  d->sides_supported = d->sides_default = PAPPL_SIDES_ONE_SIDED;
  return true;
}

int main(int argc, char **argv) {
  pappl_system_t *system;
  pappl_printer_t *printer;
  pappl_pr_driver_t entry = {"select", "HP Sprocket Select", "MFG:HP;MDL:Sprocket Select;", NULL};
  int port;
  if (argc == 2 && !strcmp(argv[1], "--version")) { puts("zink-ipp 0.1 (PAPPL bridge)"); return 0; }
  if (argc != 7) { fprintf(stderr, "Usage: zink-ipp PYTHON CONFIG JOBS-DIR SPOOL-DIR LOG PORT\n"); return 2; }
  python_exe = argv[1]; config_path = argv[2]; jobs_dir = argv[3]; port = atoi(argv[6]);
  if (port < 1024 || port > 65535 || snprintf(state_path, sizeof(state_path), "%s/queue.state", argv[4]) >= sizeof(state_path)) return 2;
  papplDeviceAddScheme("zink", PAPPL_DEVTYPE_CUSTOM_LOCAL, NULL, device_open, device_close, device_read, device_write, NULL, NULL);
  system = papplSystemCreate(PAPPL_SOPTIONS_NO_TLS | PAPPL_SOPTIONS_NO_DNS_SD,
                            "HP Sprocket Select", port, NULL, argv[4], argv[5], PAPPL_LOGLEVEL_DEBUG, NULL, false);
  if (!system) return 1;
  papplSystemSetHostName(system, "localhost");
  papplSystemSetPrinterDrivers(system, 1, &entry, NULL, NULL, driver, NULL);
  papplSystemSetSaveCallback(system, save_state, NULL);
  if (!papplSystemLoadState(system, state_path)) {
    printer = papplPrinterCreate(system, 1, "HP Sprocket Select", "select", entry.device_id, "zink://local");
    if (!printer) { papplSystemDelete(system); return 1; }
    papplPrinterSetMaxActiveJobs(printer, 1);
    papplPrinterSetMaxCompletedJobs(printer, 100);
    papplPrinterSetMaxPreservedJobs(printer, 0);
    papplSystemSetDefaultPrinterID(system, 1);
    papplSystemSaveState(system, state_path);
  }
  if (!papplSystemAddListeners(system, "127.0.0.1")) { papplSystemDelete(system); return 1; }
  papplSystemRun(system);
  papplSystemSaveState(system, state_path);
  papplSystemDelete(system);
  return 0;
}
